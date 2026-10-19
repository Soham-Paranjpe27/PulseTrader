import {
  BadRequestException,
  Injectable,
  Logger,
  NotFoundException,
  OnModuleDestroy,
  OnModuleInit,
} from '@nestjs/common';
import { AlertSeverity, Prisma } from '@prisma/client';
import { AuditService } from '../audit/audit.service';
import { LiveService } from '../live/live.service';
import { MlClient } from '../ml/ml.client';
import { PrismaService } from '../prisma/prisma.service';
import { RedisService } from '../redis/redis.service';
import { LatencyRecorder } from './latency';

const DRIFT_STATUSES = ['OK', 'WARN', 'MODEL_DRIFT_DETECTED', 'INSUFFICIENT_DATA'];
const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null;
const str = (v: unknown, max = 200) => typeof v === 'string' && v.length > 0 && v.length <= max;
const num = (v: unknown) => typeof v === 'number' && Number.isFinite(v);
const envNum = (k: string, d: number) => {
  const v = Number(process.env[k]);
  return Number.isFinite(v) && process.env[k] !== '' && process.env[k] !== undefined ? v : d;
};

export interface DriftReportInput {
  model: string;
  mode: 'LIVE' | 'REPLAY';
  status: string;
  reasons: string[];
  window: { kind: string; start: string; end: string };
  components: Record<string, unknown>;
  [k: string]: unknown;
}

/** Shape check for one drift report from the live pipeline (`ml/src/pulsetrader/monitor/live.py`). */
export function validReport(r: unknown): r is DriftReportInput {
  if (!isObj(r) || !isObj(r.window) || !isObj(r.components)) return false;
  const w = r.window;
  return (
    str(r.model) &&
    (r.mode === 'LIVE' || r.mode === 'REPLAY') &&
    DRIFT_STATUSES.includes(r.status as string) &&
    Array.isArray(r.reasons) &&
    r.reasons.every((x) => str(x)) &&
    str(w.kind, 40) &&
    [w.start, w.end].every((d) => str(d, 40) && !Number.isNaN(Date.parse(d as string)))
  );
}

/** NSE cash session in IST (Mon-Fri 09:15-15:30); exchange holidays are not known here. */
export function marketOpen(now = new Date()): boolean {
  const ist = new Date(now.getTime() + 330 * 60_000);
  const day = ist.getUTCDay();
  const mins = ist.getUTCHours() * 60 + ist.getUTCMinutes();
  return day >= 1 && day <= 5 && mins >= 9 * 60 + 15 && mins <= 15 * 60 + 30;
}

type Check = { severity: AlertSeverity; message: string; details?: object } | null;

/**
 * Phase 19 monitoring: stores drift reports from the live pipeline, runs health checks on a timer
 * (database, Redis, ML service, market data feed, latency) and keeps system alerts: one open alert per
 * (kind, key), updated while the problem lasts and resolved automatically once the check passes.
 * Drift alerts never change the model; promotion and retirement stay manual (registry).
 */
@Injectable()
export class MonitoringService implements OnModuleInit, OnModuleDestroy {
  private readonly log = new Logger(MonitoringService.name);
  private timer: NodeJS.Timeout | null = null;
  private inflight: ReturnType<MonitoringService['runCheck']> | null = null;
  private last: Record<string, unknown> | null = null;

  constructor(
    private readonly prisma: PrismaService,
    private readonly redis: RedisService,
    private readonly ml: MlClient,
    private readonly live: LiveService,
    private readonly latency: LatencyRecorder,
    private readonly audit: AuditService,
  ) {}

  onModuleInit() {
    const seconds = envNum('MONITOR_INTERVAL_SECONDS', 60);
    if (seconds > 0) {
      this.timer = setInterval(
        () => void this.check().catch((e) => this.log.error(String(e))),
        seconds * 1000,
      );
      this.timer.unref();
    }
  }

  onModuleDestroy() {
    if (this.timer) clearInterval(this.timer);
  }

  // --- alerts -------------------------------------------------------------------------------------
  async raise(kind: string, key: string, severity: AlertSeverity, message: string, details?: object) {
    const open = await this.prisma.systemAlert.findFirst({ where: { kind, key, open: true } });
    const data = { severity, message, details: (details ?? Prisma.JsonNull) as Prisma.InputJsonValue };
    if (open)
      return this.prisma.systemAlert.update({
        where: { id: open.id },
        data: { ...data, count: { increment: 1 }, lastSeen: new Date() },
      });
    const a = await this.prisma.systemAlert.create({ data: { kind, key, ...data } });
    this.log.warn(`ALERT ${severity} ${kind} ${key}: ${message}`);
    await this.audit.record('system_alert.raised', {
      entity: 'SystemAlert',
      entityId: a.id,
      detail: { kind, key },
    });
    return a;
  }

  async resolveOpen(kind: string, key: string, by = 'auto') {
    const r = await this.prisma.systemAlert.updateMany({
      where: { kind, key, open: true },
      data: { open: false, resolvedAt: new Date(), resolvedBy: by },
    });
    return r.count;
  }

  async resolveById(id: string, userId: string) {
    const a = await this.prisma.systemAlert.findUnique({ where: { id } });
    if (!a) throw new NotFoundException({ code: 'NOT_FOUND', message: `unknown alert ${id}` });
    const r = await this.prisma.systemAlert.update({
      where: { id },
      data: { open: false, resolvedAt: new Date(), resolvedBy: userId },
    });
    await this.audit.record('system_alert.resolved', { userId, entity: 'SystemAlert', entityId: id });
    return r;
  }

  alerts(open?: boolean, limit = 100) {
    return this.prisma.systemAlert.findMany({
      where: open === undefined ? {} : { open },
      orderBy: { lastSeen: 'desc' },
      take: Math.min(Math.max(limit, 1), 500),
    });
  }

  private async apply(checks: { kind: string; key: string; result: Check }[]) {
    for (const c of checks) {
      if (c.result) await this.raise(c.kind, c.key, c.result.severity, c.result.message, c.result.details);
      else await this.resolveOpen(c.kind, c.key);
    }
  }

  // --- drift reports ------------------------------------------------------------------------------
  async ingestReports(body: unknown) {
    const list = isObj(body) && Array.isArray(body.reports) ? body.reports : null;
    if (!list || list.length === 0 || list.length > 20)
      throw new BadRequestException('reports must be a non-empty array of at most 20');
    const bad = list.findIndex((r) => !validReport(r));
    if (bad >= 0) throw new BadRequestException(`report ${bad} is malformed`);
    for (const r of list as DriftReportInput[]) {
      await this.prisma.monitoringReport.create({
        data: {
          modelKey: r.model,
          mode: r.mode,
          status: r.status,
          windowKind: r.window.kind,
          windowStart: new Date(r.window.start),
          windowEnd: new Date(r.window.end),
          report: r as unknown as Prisma.InputJsonValue,
        },
      });
      // one alert per model, mode and window length; a later OK report for the same window kind clears it.
      // last_2_sessions .. last_5_sessions are one rolling window, so they share a key.
      const kind = r.window.kind.startsWith('last_') ? 'recent_sessions' : r.window.kind;
      const key = `${r.model}|${r.mode}|${kind}`;
      if (r.status === 'MODEL_DRIFT_DETECTED')
        await this.raise(
          'MODEL_DRIFT_DETECTED',
          key,
          'CRITICAL',
          `${r.model} (${r.mode}, ${r.window.kind} ${r.window.start.slice(0, 10)}..${r.window.end.slice(0, 10)}): ${r.reasons.join(', ')}. The model is not replaced automatically; review it.`,
          { reasons: r.reasons, window: r.window },
        );
      else if (r.status === 'OK') await this.resolveOpen('MODEL_DRIFT_DETECTED', key);
    }
    return { stored: list.length };
  }

  reports(model?: string, limit = 50) {
    return this.prisma.monitoringReport.findMany({
      where: model ? { modelKey: model } : {},
      orderBy: [{ windowEnd: 'desc' }, { createdAt: 'desc' }],
      take: Math.min(Math.max(limit, 1), 200),
    });
  }

  /** Latest report per (model, mode, window kind). */
  async latestDrift() {
    const rows = await this.prisma.monitoringReport.findMany({
      orderBy: [{ windowEnd: 'desc' }, { createdAt: 'desc' }],
      take: 200,
    });
    const seen = new Map<string, (typeof rows)[number]>();
    for (const r of rows) {
      const k = `${r.modelKey}|${r.mode}|${r.windowKind}`;
      if (!seen.has(k)) seen.set(k, r);
    }
    return [...seen.values()].map((r) => ({
      id: r.id,
      model: r.modelKey,
      mode: r.mode,
      status: r.status,
      windowKind: r.windowKind,
      windowStart: r.windowStart,
      windowEnd: r.windowEnd,
      createdAt: r.createdAt,
      report: r.report,
    }));
  }

  // --- health checks ------------------------------------------------------------------------------
  /**
   * Runs every check once, updates alerts, and returns the component states. Callers that arrive while
   * a check is running share its result instead of getting the previous (stale) one.
   */
  check() {
    if (!this.inflight) {
      this.inflight = this.runCheck().finally(() => {
        this.inflight = null;
      });
    }
    return this.inflight;
  }

  private async runCheck() {
    let database = false;
    try {
      await this.prisma.$queryRaw`SELECT 1`;
      database = true;
    } catch (e) {
      this.log.error(`database check failed: ${(e as Error).message}`);
    }
    const redis = await this.redis.ping();
    const t0 = Date.now();
    let ml: Record<string, unknown> = { reachable: false };
    try {
      const ready = await this.ml.ready();
      ml = { reachable: true, responseMs: Date.now() - t0, ready };
      ml.metrics = await this.ml.metrics();
    } catch (e) {
      ml = { ...ml, error: (e as Error).message };
    }
    const feed = await this.live.status();
    const provider = process.env.MARKET_DATA_PROVIDER || null;
    const open = marketOpen();
    const api = this.latency.summary();
    const mlP95 = (ml.metrics as { request_latency_ms?: { p95?: number | null } } | undefined)
      ?.request_latency_ms?.p95;
    const apiLimit = envNum('API_LATENCY_P95_MS', 1000);
    const mlLimit = envNum('ML_LATENCY_P95_MS', 500);
    if (database) {
      await this.apply([
          {
            kind: 'ML_SERVICE_DOWN',
            key: 'ml-service',
            result: ml.reachable
              ? null
              : { severity: 'CRITICAL', message: `ML service unreachable: ${String(ml.error)}` },
          },
          {
            kind: 'REDIS_DOWN',
            key: 'redis',
            result: redis
              ? null
              : { severity: 'WARNING', message: 'Redis unreachable: live feed status and the prediction stream are unavailable' },
          },
          {
            // only while a real provider is configured and the market is open: a closed market is not an outage
            kind: 'FEED_DOWN',
            key: provider ?? 'none',
            result:
              provider && open && ['DISCONNECTED', 'STALE', 'INVALID'].includes(feed.state)
                ? { severity: 'CRITICAL', message: `market data feed ${feed.state} during market hours: ${feed.reason}`, details: { feed } }
                : null,
          },
          {
            kind: 'LATENCY_HIGH',
            key: 'api',
            result:
              api.requests >= 20 && (api.p95 ?? 0) > apiLimit
                ? { severity: 'WARNING', message: `API p95 latency ${api.p95?.toFixed(0)} ms > ${apiLimit} ms over the last 5 minutes`, details: { api } }
                : null,
          },
          {
            kind: 'LATENCY_HIGH',
            key: 'ml-service',
            result:
              num(mlP95) && (mlP95 as number) > mlLimit
                ? { severity: 'WARNING', message: `ML inference p95 latency ${(mlP95 as number).toFixed(0)} ms > ${mlLimit} ms`, details: { p95: mlP95 } }
                : null,
          },
        ]); // prettier-ignore
    }
    this.last = {
      checkedAt: new Date().toISOString(),
      database,
      redis,
      mlService: ml,
      marketData: { ...feed, providerConfigured: provider, marketOpen: open },
      api,
      thresholds: { apiLatencyP95Ms: apiLimit, mlLatencyP95Ms: mlLimit },
    };
    return this.last;
  }

  async summary() {
    const components = await this.check();
    const [openAlerts, drift] = await Promise.all([this.alerts(true, 50), this.latestDrift()]);
    const worst = drift.some((d) => d.status === 'MODEL_DRIFT_DETECTED')
      ? 'MODEL_DRIFT_DETECTED'
      : drift.some((d) => d.status === 'WARN')
        ? 'WARN'
        : drift.length
          ? 'OK'
          : 'DATA_UNAVAILABLE';
    return {
      status: openAlerts.some((a) => a.severity === 'CRITICAL')
        ? 'CRITICAL'
        : openAlerts.length
          ? 'WARNING'
          : 'OK',
      components,
      drift: { status: worst, latest: drift },
      alerts: openAlerts,
      note: drift.length
        ? null
        : 'DATA_UNAVAILABLE: no drift report yet (the live pipeline reports after each completed session)',
    };
  }
}
