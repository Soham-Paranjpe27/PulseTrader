import {
  Global,
  HttpException,
  Injectable,
  Logger,
  Module,
  ServiceUnavailableException,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';

export interface MlPrediction {
  prediction_id: string;
  symbol: string;
  prediction_timestamp: string;
  market_data_timestamp: string;
  target_timestamp: string;
  latency_ms: number;
  direction: 'UP' | 'DOWN' | 'NEUTRAL' | 'NO_PREDICTION';
  model_class: 'UP' | 'DOWN' | 'NEUTRAL';
  abstain_reason: string | null;
  raw_probability: Record<string, number>;
  calibrated_probability: Record<string, number>;
  confidence: number | null;
  prediction_horizon_minutes: number;
  label_threshold: number;
  current_price: number | null;
  predicted_price: number | null;
  predicted_return: number | null;
  model_id: string;
  model_version: number;
  model_status: 'EXPERIMENT' | 'CANDIDATE' | 'SHADOW' | 'PRODUCTION' | 'RETIRED' | 'REJECTED';
  research_only: boolean;
  feature_version: string;
  data_version: string;
  data_quality: string;
}

export interface MlPredictRequest {
  symbol: string;
  timestamp: string;
  model_id?: string;
  model_version?: number;
  task?: string;
  features?: Record<string, number | null>;
  current_price?: number;
  max_staleness_seconds?: number;
}

/** HTTP client for the Python ML service. ML-side errors keep their status and code. */
@Injectable()
export class MlClient {
  private readonly log = new Logger(MlClient.name);
  private readonly base: string;

  constructor(config: ConfigService) {
    this.base = config.getOrThrow<string>('ML_SERVICE_URL').replace(/\/$/, '');
  }

  async request<T>(path: string, init: RequestInit = {}, timeoutMs = 10_000): Promise<T> {
    let res: Response;
    try {
      res = await fetch(`${this.base}${path}`, {
        ...init,
        headers: { 'content-type': 'application/json', ...(init.headers ?? {}) },
        signal: AbortSignal.timeout(timeoutMs),
      });
    } catch (e) {
      this.log.warn(`ML service ${path} unreachable: ${(e as Error).message}`);
      throw new ServiceUnavailableException({
        code: 'ML_SERVICE_UNAVAILABLE',
        message: (e as Error).message,
      });
    }
    const text = await res.text();
    let body: unknown;
    try {
      body = text ? JSON.parse(text) : null;
    } catch (e) {
      throw new ServiceUnavailableException({
        code: 'ML_SERVICE_BAD_RESPONSE',
        message: `non-JSON response from ML service: ${(e as Error).message}`,
      });
    }
    if (!res.ok) {
      const detail = (body as { detail?: unknown } | null)?.detail;
      throw new HttpException(
        typeof detail === 'object' && detail !== null
          ? detail
          : { code: 'ML_SERVICE_ERROR', message: detail ?? text },
        res.status,
      );
    }
    return body as T;
  }

  predictBatch(items: MlPredictRequest[]): Promise<{ count: number; predictions: MlPrediction[] }> {
    return this.request('/predict/batch', { method: 'POST', body: JSON.stringify({ items }) }, 30_000);
  }

  predict(item: MlPredictRequest): Promise<MlPrediction> {
    return this.request('/predict', { method: 'POST', body: JSON.stringify(item) });
  }

  models(): Promise<{ models: Record<string, unknown>[] }> {
    return this.request('/models');
  }

  features(): Promise<{
    models: { model: string; feature_version: string; count: number; features: { name: string }[] }[];
  }> {
    return this.request('/features');
  }

  ready(): Promise<Record<string, unknown>> {
    return this.request('/ready', {}, 3_000);
  }

  bars(
    symbol: string,
    date: string,
  ): Promise<{ symbol: string; date: string; bars: Record<string, unknown>[] }> {
    return this.request(`/bars/${encodeURIComponent(symbol)}?date=${encodeURIComponent(date)}`);
  }
}

@Global()
@Module({ providers: [MlClient], exports: [MlClient] })
export class MlModule {}
