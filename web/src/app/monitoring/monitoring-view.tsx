'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { ErrorView, PageHeader, Stat } from '@/components/status';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/callout';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/table';
import { useMe } from '@/hooks/auth';
import { useMonitoring } from '@/hooks/queries';
import { post } from '@/lib/api';
import { istTime, num, pct } from '@/lib/format';
import type { DriftLatest, Level, SystemAlert } from '@/lib/types';

type Tone = 'up' | 'down' | 'warn' | 'neutral' | 'info';
const tone = (s: string): Tone =>
  s === 'OK'
    ? 'up'
    : s === 'WARN' || s === 'WARNING'
      ? 'warn'
      : s === 'INSUFFICIENT_DATA' || s === 'DATA_UNAVAILABLE'
        ? 'neutral'
        : 'down';
const ms = (v: number | null | undefined) =>
  v === null || v === undefined ? '–' : `${v.toFixed(v < 10 ? 1 : 0)} ms`;

function LevelBadge({ s, testId }: { s: string; testId?: string }) {
  return (
    <Badge tone={tone(s)} data-testid={testId}>
      {s.replaceAll('_', ' ')}
    </Badge>
  );
}

function Components() {
  const m = useMonitoring();
  if (m.isError) return <ErrorView error={m.error} />;
  if (!m.data) return <Skeleton className="h-28 w-full" />;
  const c = m.data.components;
  const mlP95 = c.mlService.metrics?.request_latency_ms?.p95;
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6" data-testid="components">
      <Stat label="Database" value={<LevelBadge s={c.database ? 'OK' : 'DOWN'} />} />
      <Stat label="Redis" value={<LevelBadge s={c.redis ? 'OK' : 'DOWN'} />} sub="feed status, SSE" />
      <Stat
        label="ML service"
        value={<LevelBadge s={c.mlService.reachable ? 'OK' : 'DOWN'} />}
        sub={c.mlService.reachable ? `inference p95 ${ms(mlP95)}` : (c.mlService.error ?? 'unreachable')}
      />
      <Stat
        label="Market data"
        value={<Badge tone={c.marketData.state === 'LIVE' ? 'up' : 'neutral'}>{c.marketData.state}</Badge>}
        sub={`${c.marketData.providerConfigured ?? 'no provider'} · market ${c.marketData.marketOpen ? 'open' : 'closed'}`}
      />
      <Stat
        label="API latency (5 min)"
        value={`p95 ${ms(c.api.p95)}`}
        sub={`p50 ${ms(c.api.p50)} · ${c.api.requests} req · ${c.api.errors5xx} 5xx`}
        testId="api-latency"
      />
      <Stat label="Checked" value={istTime(c.checkedAt)} sub="every 60 s" />
    </div>
  );
}

function threshold(v: number | null | undefined, t: [number, number] | undefined, digits = 3) {
  if (v === null || v === undefined) return '–';
  return t ? `${num(v, digits)} (warn ${num(t[0], digits)}, drift ${num(t[1], digits)})` : num(v, digits);
}

function DriftCard({ d }: { d: DriftLatest }) {
  const c = d.report.components;
  const acc = c.accuracy;
  const mcc = acc?.checks?.mcc;
  const rows: { name: string; level: Level | undefined; value: string }[] = [
    {
      name: 'Accuracy (MCC)',
      level: acc?.status,
      value: acc?.window
        ? `MCC ${num(acc.window.mcc, 3)} (warn below ${num(mcc?.warn_below, 3)}, drift below ${num(mcc?.drift_below, 3)}); accuracy ${pct(acc.window.accuracy)}, balanced ${pct(acc.window.balanced_accuracy)}, n ${acc.window.n}`
        : 'not enough outcomes',
    },
    { name: 'Calibration (ECE)', level: c.calibration?.status, value: threshold(c.calibration?.ece_top as number | undefined, c.calibration?.thresholds) },
    {
      name: 'Features (weighted PSI)',
      level: c.feature?.status,
      value: threshold(c.feature?.importance_weighted_psi, c.feature?.thresholds),
    },
    { name: 'Predictions (PSI)', level: c.prediction?.status, value: threshold(c.prediction?.max_psi, c.prediction?.thresholds) },
    { name: 'Market regime (PSI)', level: c.regime?.status, value: threshold(c.regime?.psi, c.regime?.thresholds, 2) },
  ]; // prettier-ignore
  const top = (c.feature?.top ?? []).slice(0, 5);
  return (
    <Card data-testid="drift-card">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2 text-sm">
          {d.model}
          <Badge tone={d.mode === 'LIVE' ? 'up' : 'info'}>{d.mode}</Badge>
          <LevelBadge s={d.status} testId="drift-status" />
        </CardTitle>
        <CardDescription>
          {d.windowKind === 'session' ? 'Session' : d.windowKind.replaceAll('_', ' ')}{' '}
          {d.windowStart.slice(0, 10)}
          {d.windowEnd.slice(0, 10) !== d.windowStart.slice(0, 10) ? ` to ${d.windowEnd.slice(0, 10)}` : ''}
          {d.report.reasons.length ? ` · ${d.report.reasons.join(', ')}` : ''}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <Table>
          <THead>
            <TR>
              <TH>Check</TH>
              <TH>Level</TH>
              <TH>Value (thresholds from history)</TH>
            </TR>
          </THead>
          <TBody>
            {rows.map((r) => (
              <TR key={r.name}>
                <TD className="text-xs">{r.name}</TD>
                <TD>{r.level ? <LevelBadge s={r.level} /> : '–'}</TD>
                <TD className="text-xs">{r.value}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
        {top.length ? (
          <p className="text-muted-foreground text-xs">
            Most shifted features: {top.map((t) => `${t.feature} ${num(t.psi, 2)} (${t.level})`).join(', ')}.
          </p>
        ) : null}
        {d.report.latency ? (
          <p className="text-muted-foreground text-xs">
            Inference p50 {ms(d.report.latency.inference_ms_p50)}, p95 {ms(d.report.latency.inference_ms_p95)}
            ; feature build p95 {num(d.report.latency.feature_build_seconds_p95, 2)} s per sampled minute.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function Alerts({ alerts }: { alerts: SystemAlert[] }) {
  const me = useMe();
  const qc = useQueryClient();
  const resolve = useMutation({
    mutationFn: (id: string) => post(`/monitoring/alerts/${id}/resolve`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['monitoring'] }),
  });
  if (!alerts.length)
    return (
      <p className="text-muted-foreground text-sm" data-testid="no-alerts">
        No open system alerts.
      </p>
    );
  return (
    <Table data-testid="system-alerts">
      <THead>
        <TR>
          <TH>Severity</TH>
          <TH>Kind</TH>
          <TH>Message</TH>
          <TH className="text-right">Seen</TH>
          <TH>Last seen</TH>
          <TH />
        </TR>
      </THead>
      <TBody>
        {alerts.map((a) => (
          <TR key={a.id}>
            <TD>
              <LevelBadge s={a.severity} />
            </TD>
            <TD className="text-xs">{a.kind}</TD>
            <TD className="text-xs">{a.message}</TD>
            <TD className="text-right">{a.count}</TD>
            <TD className="text-xs">{istTime(a.lastSeen)}</TD>
            <TD>
              {me.data?.role === 'ADMIN' ? (
                <Button
                  size="sm"
                  variant="outline"
                  disabled={resolve.isPending}
                  onClick={() => resolve.mutate(a.id)}
                >
                  Resolve
                </Button>
              ) : null}
            </TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

export function MonitoringView() {
  const m = useMonitoring();
  return (
    <>
      <PageHeader
        title="Monitoring"
        description="Health, latency, model drift and system alerts. Drift never replaces a model automatically."
      />
      <div className="flex flex-col gap-4">
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle>System</CardTitle>
            {m.data ? <LevelBadge s={m.data.status} testId="system-status" /> : null}
          </CardHeader>
          <CardContent>
            <Components />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              Model drift {m.data ? <LevelBadge s={m.data.drift.status} testId="drift-overall" /> : null}
            </CardTitle>
            <CardDescription>
              Checked after each completed session against references from training data and earlier
              out-of-sample folds. A check is WARN or DRIFT when the window is more extreme than 95% or 99% of
              historical windows of the same length. MODEL_DRIFT_DETECTED means accuracy or calibration
              degraded, or features and predictions both shifted.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {m.data?.drift.latest.length ? (
              <div className="grid gap-4 lg:grid-cols-2">
                {m.data.drift.latest.map((d) => (
                  <DriftCard key={d.id} d={d} />
                ))}
              </div>
            ) : (
              <p className="text-muted-foreground text-sm">{m.data?.note ?? ' '}</p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Open system alerts</CardTitle>
            <CardDescription>
              Raised by the checks; resolved automatically once the check passes again.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {m.data ? <Alerts alerts={m.data.alerts} /> : <Skeleton className="h-16 w-full" />}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
