import { Injectable, Logger } from '@nestjs/common';
import { ModelStatus, Prisma } from '@prisma/client';
import { MlClient } from '../ml/ml.client';
import { PrismaService } from '../prisma/prisma.service';

interface RegistryRow {
  model_id: string;
  version: number;
  status: ModelStatus;
  task: string;
  created_at: string;
  accuracy_gate: string;
  validation: Record<string, number | null>;
  backtest_gated_after_costs: Record<string, number | null>;
  gates: Record<string, string>;
  serving?: Record<string, unknown>;
  model_type: string;
  dataset_version: string;
  feature_version: string;
  label_version: string;
  training_period: Prisma.InputJsonValue;
  validation_period: Prisma.InputJsonValue;
  test_period: Prisma.InputJsonValue;
  hyperparameters: Prisma.InputJsonValue;
  calibration_version: string | null;
  artifact_path: string;
  history: Prisma.InputJsonValue;
}

/** Mirrors the ML registry into ModelVersion/FeatureVersion rows (the registry stays the source of truth). */
@Injectable()
export class ModelsService {
  private readonly log = new Logger(ModelsService.name);

  constructor(
    private readonly prisma: PrismaService,
    private readonly ml: MlClient,
  ) {}

  async sync(): Promise<{ models: number; featureVersions: number }> {
    const { models } = (await this.ml.models()) as unknown as { models: RegistryRow[] };
    for (const m of models) {
      const id = `${m.model_id}@v${m.version}`;
      const data = {
        modelId: m.model_id,
        version: m.version,
        task: m.task,
        modelType: m.model_type,
        status: m.status,
        datasetVersion: m.dataset_version,
        featureVersion: m.feature_version,
        labelVersion: m.label_version,
        trainingPeriod: m.training_period,
        validationPeriod: m.validation_period,
        testPeriod: m.test_period,
        hyperparameters: m.hyperparameters,
        metrics: { validation: m.validation } as Prisma.InputJsonValue,
        backtestMetrics: { gated_after_costs: m.backtest_gated_after_costs } as Prisma.InputJsonValue,
        calibrationVersion: m.calibration_version,
        artifactPath: m.artifact_path,
        gates: m.gates,
        accuracyGate: m.accuracy_gate,
        history: m.history,
        createdAt: new Date(m.created_at),
        syncedAt: new Date(),
      };
      await this.prisma.modelVersion.upsert({ where: { id }, create: { id, ...data }, update: data });
    }
    const feats = await this.ml.features();
    const seen = new Set<string>();
    for (const f of feats.models) {
      if (seen.has(f.feature_version)) continue;
      seen.add(f.feature_version);
      const names = f.features.map((x) => x.name);
      await this.prisma.featureVersion.upsert({
        where: { version: f.feature_version },
        create: { version: f.feature_version, features: names, count: names.length },
        update: { features: names, count: names.length },
      });
    }
    this.log.log(`synced ${models.length} model versions, ${seen.size} feature versions`);
    return { models: models.length, featureVersions: seen.size };
  }

  async ensure(id: string): Promise<void> {
    if (!(await this.prisma.modelVersion.findUnique({ where: { id } }))) await this.sync();
  }

  list() {
    return this.prisma.modelVersion.findMany({ orderBy: [{ modelId: 'asc' }, { version: 'desc' }] });
  }

  async active() {
    const rows = await this.prisma.modelVersion.findMany({ where: { status: 'PRODUCTION' } });
    return {
      active: rows,
      reason: rows.length ? null : 'NO_PRODUCTION_MODEL: no model has passed the production gates',
    };
  }
}
