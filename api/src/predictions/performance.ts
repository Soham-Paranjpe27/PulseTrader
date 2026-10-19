/**
 * Live performance of stored predictions with known outcomes (spec section 48). Same definitions as
 * the ML evaluation (`ml/src/pulsetrader/live/evaluate.py`):
 * - full coverage: the model's argmax class vs the realised class (3 classes) -> accuracy, balanced
 *   accuracy, MCC, Brier and top-class ECE of the raw and calibrated probabilities;
 * - selective (what users see): coverage = UP/DOWN calls / evaluated predictions, and the accuracy,
 *   balanced accuracy and MCC of those calls; rolling accuracy over the last 20/50/100/500 calls;
 *   daily / weekly / monthly accuracy (Indian market dates).
 * Predictions whose label is unavailable (the target bar does not exist) are counted but not scored.
 */

export type Cls = 'DOWN' | 'NEUTRAL' | 'UP';
const CLASSES: Cls[] = ['DOWN', 'NEUTRAL', 'UP'];
const isCls = (v: unknown): v is Cls => CLASSES.includes(v as Cls);

export interface OutcomeRow {
  ts: Date; // market data timestamp
  direction: string; // UP | DOWN | NEUTRAL | NO_PREDICTION (served call)
  modelClass: string; // argmax class
  actualClass: string | null;
  directionCorrect: boolean | null;
  rawProbability: unknown;
  calibratedProbability: unknown;
}

export interface ClassMetrics {
  n: number;
  accuracy: number | null;
  balancedAccuracy: number | null;
  mcc: number | null;
}

export interface PeriodAccuracy {
  period: string;
  evaluated: number;
  calls: number;
  coverage: number | null;
  accuracy: number | null;
}

export interface Performance {
  predictions: number;
  evaluated: number;
  labelUnavailable: number;
  fullCoverage: ClassMetrics & { brier: number | null; ece: number | null };
  calibrated: { brier: number | null; ece: number | null };
  selective: ClassMetrics & { calls: number; coverage: number | null };
  rolling: Record<string, { n: number; accuracy: number | null }>;
  daily: PeriodAccuracy[];
  weekly: PeriodAccuracy[];
  monthly: PeriodAccuracy[];
}

/** Accuracy, balanced accuracy (mean recall over classes present) and multiclass MCC (Gorodkin). */
export function classMetrics(y: Cls[], p: Cls[]): ClassMetrics {
  const n = y.length;
  if (!n) return { n, accuracy: null, balancedAccuracy: null, mcc: null };
  const k = CLASSES.length;
  const cm = Array.from({ length: k }, () => new Array<number>(k).fill(0));
  y.forEach((t, i) => cm[CLASSES.indexOf(t)][CLASSES.indexOf(p[i])]++);
  const t = cm.map((r) => r.reduce((a, b) => a + b, 0));
  const q = CLASSES.map((_, j) => cm.reduce((a, r) => a + r[j], 0));
  const c = CLASSES.reduce((a, _, i) => a + cm[i][i], 0);
  const recalls = CLASSES.map((_, i) => (t[i] ? cm[i][i] / t[i] : null)).filter((r) => r !== null);
  const num = c * n - q.reduce((a, qk, i) => a + qk * t[i], 0);
  const den = Math.sqrt(
    (n * n - q.reduce((a, v) => a + v * v, 0)) * (n * n - t.reduce((a, v) => a + v * v, 0)),
  );
  return {
    n,
    accuracy: c / n,
    balancedAccuracy: recalls.reduce((a, b) => a + b, 0) / recalls.length,
    mcc: den ? num / den : 0,
  };
}

function probs(v: unknown): number[] | null {
  if (typeof v !== 'object' || v === null) return null;
  const o = v as Record<string, unknown>;
  const p = ['down', 'neutral', 'up'].map((c) => o[c]);
  return p.every((x) => typeof x === 'number' && Number.isFinite(x)) ? (p as number[]) : null;
}

/** Multiclass Brier score and top-class expected calibration error (10 equal-width bins). */
export function calibration(
  y: Cls[],
  prob: number[][],
  bins = 10,
): { brier: number | null; ece: number | null } {
  if (!y.length) return { brier: null, ece: null };
  let brier = 0;
  const conf = new Array<number>(bins).fill(0);
  const hit = new Array<number>(bins).fill(0);
  const cnt = new Array<number>(bins).fill(0);
  y.forEach((t, i) => {
    const p = prob[i];
    const ti = CLASSES.indexOf(t);
    brier += p.reduce((a, v, j) => a + (v - (j === ti ? 1 : 0)) ** 2, 0);
    const top = p.indexOf(Math.max(...p));
    const b = Math.min(bins - 1, Math.floor(p[top] * bins));
    conf[b] += p[top];
    hit[b] += top === ti ? 1 : 0;
    cnt[b]++;
  });
  const ece = cnt.reduce((a, c, b) => a + (c ? Math.abs(hit[b] - conf[b]) : 0), 0) / y.length;
  return { brier: brier / y.length, ece };
}

/** Indian market date (UTC+5:30, no DST). */
const istDate = (d: Date) => new Date(d.getTime() + 330 * 60_000).toISOString().slice(0, 10);

export function isoWeek(day: string): string {
  const d = new Date(`${day}T00:00:00Z`);
  const wd = (d.getUTCDay() + 6) % 7; // Monday = 0
  d.setUTCDate(d.getUTCDate() - wd + 3); // Thursday of this week decides the ISO year
  const year = d.getUTCFullYear();
  const week = 1 + Math.floor((d.getTime() - Date.UTC(year, 0, 1)) / 86_400_000 / 7);
  return `${year}-W${String(week).padStart(2, '0')}`;
}

const callOk = (r: OutcomeRow) => r.directionCorrect === true;

function byPeriod(known: OutcomeRow[], key: (r: OutcomeRow) => string): PeriodAccuracy[] {
  const groups = new Map<string, OutcomeRow[]>();
  for (const r of known) {
    const k = key(r);
    const g = groups.get(k);
    if (g) g.push(r);
    else groups.set(k, [r]);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => (a < b ? -1 : 1))
    .map(([period, rows]) => {
      const calls = rows.filter((r) => r.direction === 'UP' || r.direction === 'DOWN');
      return {
        period,
        evaluated: rows.length,
        calls: calls.length,
        coverage: rows.length ? calls.length / rows.length : null,
        accuracy: calls.length ? calls.filter(callOk).length / calls.length : null,
      };
    });
}

export function performance(rows: OutcomeRow[], windows = [20, 50, 100, 500]): Performance {
  const sorted = [...rows].sort((a, b) => a.ts.getTime() - b.ts.getTime());
  const known = sorted.filter((r) => isCls(r.actualClass) && isCls(r.modelClass));
  const y = known.map((r) => r.actualClass as Cls);
  const full = classMetrics(
    y,
    known.map((r) => r.modelClass as Cls),
  );
  const withRaw = known.filter((r) => probs(r.rawProbability));
  const withCal = known.filter((r) => probs(r.calibratedProbability));
  const raw = calibration(
    withRaw.map((r) => r.actualClass as Cls),
    withRaw.map((r) => probs(r.rawProbability) as number[]),
  );
  const cal = calibration(
    withCal.map((r) => r.actualClass as Cls),
    withCal.map((r) => probs(r.calibratedProbability) as number[]),
  );
  const calls = known.filter((r) => r.direction === 'UP' || r.direction === 'DOWN');
  const sel = classMetrics(
    calls.map((r) => r.actualClass as Cls),
    calls.map((r) => r.direction as Cls),
  );
  const rolling: Performance['rolling'] = {};
  for (const w of windows) {
    const s = calls.slice(-w);
    rolling[`last_${w}`] = { n: s.length, accuracy: s.length ? s.filter(callOk).length / s.length : null };
  }
  return {
    predictions: rows.length,
    evaluated: known.length,
    labelUnavailable: rows.length - known.length,
    fullCoverage: { ...full, brier: raw.brier, ece: raw.ece },
    calibrated: cal,
    // a call is right only when the realised class equals it (an actual NEUTRAL counts as wrong)
    selective: { ...sel, calls: calls.length, coverage: known.length ? calls.length / known.length : null },
    rolling,
    daily: byPeriod(known, (r) => istDate(r.ts)),
    weekly: byPeriod(known, (r) => isoWeek(istDate(r.ts))),
    monthly: byPeriod(known, (r) => istDate(r.ts).slice(0, 7)),
  };
}
