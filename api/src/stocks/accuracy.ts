import { Prisma } from '@prisma/client';
import { PrismaService } from '../prisma/prisma.service';

/** Direction accuracy over the most recent evaluated directional calls (never over abstentions). */
export async function recentAccuracy(
  prisma: PrismaService,
  where: Prisma.PredictionWhereInput,
  windows = [20, 50, 100, 500],
) {
  const rows = await prisma.prediction.findMany({
    where: { ...where, direction: { in: ['UP', 'DOWN'] }, outcome: { isNot: null } },
    orderBy: { predictionTimestamp: 'desc' },
    take: Math.max(...windows),
    select: { outcome: { select: { directionCorrect: true } } },
  });
  const out: Record<string, { n: number; accuracy: number | null }> = {};
  for (const w of windows) {
    const s = rows
      .slice(0, w)
      .filter((r) => r.outcome?.directionCorrect !== null && r.outcome?.directionCorrect !== undefined);
    out[`last_${w}`] = {
      n: s.length,
      accuracy: s.length ? s.filter((r) => r.outcome?.directionCorrect).length / s.length : null,
    };
  }
  return out;
}
