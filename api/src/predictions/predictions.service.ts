import { Injectable, Logger, NotFoundException } from '@nestjs/common';
import { Prediction, Prisma } from '@prisma/client';
import { filter, map, merge, Observable, Subject } from 'rxjs';
import { MlClient, MlPrediction } from '../ml/ml.client';
import { ModelsService } from '../models/models.service';
import { PrismaService } from '../prisma/prisma.service';
import { RedisService } from '../redis/redis.service';
import { recentAccuracy } from '../stocks/accuracy';
import { CreatePredictionDto } from './predictions.dto';

/** Stores ML-service predictions and fans them out to SSE subscribers. */
@Injectable()
export class PredictionsService {
  private readonly log = new Logger(PredictionsService.name);
  private readonly local = new Subject<Prediction>();

  constructor(
    private readonly prisma: PrismaService,
    private readonly ml: MlClient,
    private readonly models: ModelsService,
    private readonly redis: RedisService,
  ) {}

  async create(input: CreatePredictionDto[], userId: string): Promise<Prediction[]> {
    const items = input.map((i) => ({ ...i, symbol: i.symbol.toUpperCase() }));
    const symbols = [...new Set(items.map((i) => i.symbol))];
    const known = await this.prisma.stock.findMany({
      where: { symbol: { in: symbols } },
      select: { symbol: true },
    });
    const missing = symbols.filter((s) => !known.some((k) => k.symbol === s));
    if (missing.length)
      throw new NotFoundException({
        code: 'DATA_UNAVAILABLE',
        message: `unknown symbols ${missing.join(', ')}`,
      });
    const res = await this.ml.predictBatch(
      items.map((i) => ({
        symbol: i.symbol,
        timestamp: i.timestamp,
        model_id: i.modelId,
        model_version: i.modelVersion,
        task: i.task,
      })),
    );
    const saved: Prediction[] = [];
    for (const p of res.predictions) {
      const mv = `${p.model_id}@v${p.model_version}`;
      await this.models.ensure(mv);
      const row = await this.prisma.prediction.create({ data: toRow(p, mv, userId) });
      saved.push(row);
      if (!(await this.redis.publish('predictions', row))) this.local.next(row);
    }
    return saved;
  }

  /** Predictions made by the live pipeline (LIVE or REPLAY mode); idempotent on prediction_id. */
  async ingest(preds: MlPrediction[], mode: 'LIVE' | 'REPLAY'): Promise<number> {
    const known = new Set(
      (
        await this.prisma.stock.findMany({
          where: { symbol: { in: [...new Set(preds.map((p) => p.symbol))] } },
          select: { symbol: true },
        })
      ).map((s) => s.symbol),
    );
    const rows: Prisma.PredictionUncheckedCreateInput[] = [];
    for (const p of preds.filter((x) => known.has(x.symbol))) {
      const mv = `${p.model_id}@v${p.model_version}`;
      await this.models.ensure(mv);
      rows.push(toRow(p, mv, null, mode));
    }
    const { count } = await this.prisma.prediction.createMany({ data: rows, skipDuplicates: true });
    for (const row of rows) {
      const out = { ...row, createdAt: new Date() } as unknown as Prediction;
      if (!(await this.redis.publish('predictions', out))) this.local.next(out);
    }
    if (rows.length < preds.length)
      this.log.warn(`ingest skipped ${preds.length - rows.length} predictions for unknown symbols`);
    return count;
  }

  async list(
    where: { symbol?: string; modelVersionId?: string; direction?: string },
    page: number,
    size: number,
  ) {
    const w: Prisma.PredictionWhereInput = {
      ...(where.symbol ? { symbol: where.symbol } : {}),
      ...(where.modelVersionId ? { modelVersionId: where.modelVersionId } : {}),
      ...(where.direction ? { direction: where.direction as Prediction['direction'] } : {}),
    };
    const [total, items] = await Promise.all([
      this.prisma.prediction.count({ where: w }),
      this.prisma.prediction.findMany({
        where: w,
        orderBy: { predictionTimestamp: 'desc' },
        skip: (page - 1) * size,
        take: size,
        include: { outcome: true },
      }),
    ]);
    return { total, page, pageSize: size, items };
  }

  async get(id: string) {
    const p = await this.prisma.prediction.findUnique({
      where: { id },
      include: { outcome: true, modelVersion: true },
    });
    if (!p) throw new NotFoundException({ code: 'DATA_UNAVAILABLE', message: `unknown prediction ${id}` });
    return p;
  }

  async accuracy(symbol?: string, modelVersionId?: string) {
    const where: Prisma.PredictionWhereInput = {
      ...(symbol ? { symbol } : {}),
      ...(modelVersionId ? { modelVersionId } : {}),
    };
    const [total, directional, evaluated] = await Promise.all([
      this.prisma.prediction.count({ where }),
      this.prisma.prediction.count({ where: { ...where, direction: { in: ['UP', 'DOWN'] } } }),
      this.prisma.prediction.count({
        where: { ...where, direction: { in: ['UP', 'DOWN'] }, outcome: { isNot: null } },
      }),
    ]);
    return {
      predictions: total,
      directional,
      coverage: total ? directional / total : null,
      evaluated,
      rolling: await recentAccuracy(this.prisma, where),
      note: evaluated
        ? null
        : 'DATA_UNAVAILABLE: no prediction outcomes evaluated yet (live evaluation is Phase 18)',
    };
  }

  stream(): Observable<{ data: object }> {
    const remote = this.redis.stream().pipe(
      filter((e) => e.channel === 'predictions'),
      map((e) => JSON.parse(e.message) as object),
    );
    return merge(remote, this.local.asObservable()).pipe(map((data) => ({ data })));
  }
}

function toRow(
  p: MlPrediction,
  modelVersionId: string,
  userId: string | null,
  mode?: 'LIVE' | 'REPLAY',
): Prisma.PredictionUncheckedCreateInput {
  return {
    id: p.prediction_id,
    symbol: p.symbol,
    predictionTimestamp: new Date(p.prediction_timestamp),
    marketDataTimestamp: new Date(p.market_data_timestamp),
    targetTimestamp: new Date(p.target_timestamp),
    latencyMs: p.latency_ms,
    currentPrice: p.current_price,
    predictedPrice: p.predicted_price,
    predictedReturn: p.predicted_return,
    direction: p.direction,
    modelClass: p.model_class,
    abstainReason: p.abstain_reason,
    rawProbability: p.raw_probability,
    calibratedProbability: p.calibrated_probability,
    confidence: p.confidence,
    horizonMinutes: p.prediction_horizon_minutes,
    labelThreshold: p.label_threshold,
    modelVersionId,
    modelStatus: p.model_status,
    researchOnly: p.research_only,
    featureVersion: p.feature_version,
    dataVersion: p.data_version,
    dataQuality: p.data_quality,
    // only the token-authenticated live pipeline can store LIVE (or REPLAY) predictions
    mode: mode ?? (p.data_quality.startsWith('VALIDATED_HISTORICAL') ? 'HISTORICAL' : 'CLIENT_FEATURES'),
    requestedById: userId,
  };
}
