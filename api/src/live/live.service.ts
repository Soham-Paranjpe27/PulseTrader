import { BadRequestException, Injectable } from '@nestjs/common';
import { MlPrediction } from '../ml/ml.client';
import { OutcomeInput, PredictionsService } from '../predictions/predictions.service';
import { RedisService } from '../redis/redis.service';

export type FeedState = 'LIVE' | 'DELAYED' | 'STALE' | 'DISCONNECTED' | 'INVALID' | 'REPLAY';
const STATES: FeedState[] = ['LIVE', 'DELAYED', 'STALE', 'DISCONNECTED', 'INVALID', 'REPLAY'];

export interface LiveStatus {
  state: FeedState;
  provider: string | null;
  mode: 'LIVE' | 'REPLAY' | null;
  reason: string;
  lastBarClose: string | null;
  latencyP50Seconds: number | null;
  accepted: number | null;
  rejected: Record<string, number> | null;
  observedAt: string | null;
}

export interface LivePrice {
  ts: string;
  close: number;
}

interface StoredStatus extends LiveStatus {
  prices?: Record<string, LivePrice>;
}

const key = () => process.env.LIVE_STATUS_KEY || 'live:status';
/** The pipeline reports every minute (live: every 15 s); an older report means it stopped. */
export const STATUS_TTL_SECONDS = 120;

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null;
const num = (v: unknown) => typeof v === 'number' && Number.isFinite(v);
const str = (v: unknown) => typeof v === 'string' && v.length > 0 && v.length < 200;

/** Shape check for one prediction from the live pipeline (the token already authenticated the sender). */
export function validPrediction(p: unknown): p is MlPrediction {
  if (!isObj(p)) return false;
  return (
    str(p.prediction_id) &&
    str(p.symbol) &&
    ['prediction_timestamp', 'market_data_timestamp', 'target_timestamp'].every(
      (k) => str(p[k]) && !Number.isNaN(Date.parse(p[k] as string)),
    ) &&
    ['UP', 'DOWN', 'NEUTRAL', 'NO_PREDICTION'].includes(p.direction as string) &&
    ['UP', 'DOWN', 'NEUTRAL'].includes(p.model_class as string) &&
    isObj(p.raw_probability) &&
    isObj(p.calibrated_probability) &&
    num(p.latency_ms) &&
    num(p.prediction_horizon_minutes) &&
    num(p.label_threshold) &&
    str(p.model_id) &&
    num(p.model_version) &&
    str(p.model_status) &&
    typeof p.research_only === 'boolean' &&
    str(p.feature_version) &&
    str(p.data_version) &&
    str(p.data_quality) &&
    (p.mode === 'LIVE' || p.mode === 'REPLAY')
  );
}

const numOrNull = (v: unknown) => v === null || num(v);

/** Shape check for one realised outcome (`live/outcomes.py`). */
export function validOutcome(o: unknown): o is OutcomeInput {
  if (!isObj(o)) return false;
  return (
    str(o.prediction_id) &&
    numOrNull(o.actual_price) &&
    numOrNull(o.actual_return) &&
    numOrNull(o.prediction_error) &&
    (o.actual_class === null || ['UP', 'DOWN', 'NEUTRAL'].includes(o.actual_class as string)) &&
    (o.direction_correct === null || typeof o.direction_correct === 'boolean') &&
    // no outcome without a label: correctness needs a realised class
    (o.direction_correct === null || o.actual_class !== null)
  );
}

/**
 * Feed status and predictions pushed by the live pipeline (`pulsetrader live`). The state shown to
 * users is the pipeline's own validated state; with no fresh report the feed is DISCONNECTED. A
 * connected browser never makes it LIVE, and recorded (replayed) data is always REPLAY.
 */
@Injectable()
export class LiveService {
  constructor(
    private readonly redis: RedisService,
    private readonly preds: PredictionsService,
  ) {}

  private async stored(): Promise<StoredStatus | null> {
    return this.redis.getJson<StoredStatus>(key());
  }

  async status(): Promise<LiveStatus> {
    const s = await this.stored();
    const configured = process.env.MARKET_DATA_PROVIDER || null;
    if (!s) {
      return {
        state: 'DISCONNECTED',
        provider: configured,
        mode: null,
        reason: configured
          ? `provider ${configured} configured but the live pipeline is not reporting`
          : 'no live market data provider configured',
        lastBarClose: null,
        latencyP50Seconds: null,
        accepted: null,
        rejected: null,
        observedAt: null,
      };
    }
    const status: LiveStatus = {
      state: s.state,
      provider: s.provider,
      mode: s.mode,
      reason: s.reason,
      lastBarClose: s.lastBarClose,
      latencyP50Seconds: s.latencyP50Seconds,
      accepted: s.accepted,
      rejected: s.rejected,
      observedAt: s.observedAt,
    };
    // a replay can never be shown as LIVE, whatever the report says
    if (status.mode !== 'LIVE' && status.state !== 'DISCONNECTED') status.state = 'REPLAY';
    return status;
  }

  async price(symbol: string): Promise<(LivePrice & { state: FeedState; mode: string | null }) | null> {
    const s = await this.stored();
    const p = s?.prices?.[symbol];
    if (!s || !p) return null;
    const { state } = await this.status();
    return { ...p, state, mode: s.mode };
  }

  async setStatus(body: unknown): Promise<LiveStatus> {
    if (!isObj(body) || !STATES.includes(body.state as FeedState) || !str(body.provider))
      throw new BadRequestException('status needs state and provider');
    const mode = body.mode === 'LIVE' ? 'LIVE' : 'REPLAY';
    const prices: Record<string, LivePrice> = {};
    if (isObj(body.prices))
      for (const [k, v] of Object.entries(body.prices).slice(0, 5000))
        if (isObj(v) && str(v.ts) && num(v.close))
          prices[k] = { ts: v.ts as string, close: v.close as number };
    const stored: StoredStatus = {
      state: body.state as FeedState,
      provider: body.provider as string,
      mode,
      reason: str(body.reason) ? (body.reason as string) : '',
      lastBarClose: str(body.lastBarClose) ? (body.lastBarClose as string) : null,
      latencyP50Seconds: num(body.latencyP50Seconds) ? (body.latencyP50Seconds as number) : null,
      accepted: num(body.accepted) ? (body.accepted as number) : null,
      rejected: isObj(body.rejected) ? (body.rejected as Record<string, number>) : null,
      observedAt: str(body.observedAt) ? (body.observedAt as string) : new Date().toISOString(),
      prices,
    };
    await this.redis.setJson(key(), stored, STATUS_TTL_SECONDS);
    return this.status();
  }

  async ingest(body: unknown): Promise<{ received: number; stored: number }> {
    const list = isObj(body) && Array.isArray(body.predictions) ? body.predictions : null;
    if (!list || list.length === 0 || list.length > 500)
      throw new BadRequestException('predictions must be a non-empty array of at most 500');
    const bad = list.findIndex((p) => !validPrediction(p));
    if (bad >= 0) throw new BadRequestException(`prediction ${bad} is malformed`);
    const preds = list as (MlPrediction & { mode: 'LIVE' | 'REPLAY' })[];
    let stored = 0;
    for (const mode of ['LIVE', 'REPLAY'] as const) {
      const group = preds.filter((p) => p.mode === mode);
      if (group.length) stored += await this.preds.ingest(group, mode);
    }
    return { received: preds.length, stored };
  }

  async outcomes(body: unknown): Promise<{ received: number; stored: number; unknown: number }> {
    const list = isObj(body) && Array.isArray(body.outcomes) ? body.outcomes : null;
    if (!list || list.length === 0 || list.length > 500)
      throw new BadRequestException('outcomes must be a non-empty array of at most 500');
    const bad = list.findIndex((o) => !validOutcome(o));
    if (bad >= 0) throw new BadRequestException(`outcome ${bad} is malformed`);
    return { received: list.length, ...(await this.preds.storeOutcomes(list as OutcomeInput[])) };
  }
}
