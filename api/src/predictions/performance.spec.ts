import { Cls, OutcomeRow, calibration, classMetrics, isoWeek, performance } from './performance';

describe('classMetrics', () => {
  it('matches scikit-learn accuracy, balanced accuracy and multiclass MCC', () => {
    const y: Cls[] = ['UP', 'DOWN', 'NEUTRAL', 'UP', 'UP', 'DOWN', 'NEUTRAL', 'DOWN'];
    const p: Cls[] = ['UP', 'NEUTRAL', 'NEUTRAL', 'DOWN', 'UP', 'DOWN', 'UP', 'DOWN'];
    const m = classMetrics(y, p);
    // sklearn: 0.625, 0.6111111111, 0.4285714286
    expect(m.accuracy).toBeCloseTo(0.625, 10);
    expect(m.balancedAccuracy).toBeCloseTo(0.611111111111, 10);
    expect(m.mcc).toBeCloseTo(0.428571428571, 10);
  });
  it('is empty-safe and gives MCC 0 for a constant prediction', () => {
    expect(classMetrics([], []).accuracy).toBeNull();
    expect(classMetrics(['UP', 'DOWN'], ['UP', 'UP']).mcc).toBe(0);
  });
});

describe('calibration and dates', () => {
  it('Brier and top-class ECE', () => {
    const c = calibration(
      ['UP', 'DOWN'],
      [
        [0.1, 0.1, 0.8],
        [0.2, 0.2, 0.6],
      ],
    );
    expect(c.brier).toBeCloseTo((0.01 + 0.01 + 0.04 + (0.64 + 0.04 + 0.36)) / 2, 10);
    // bins 0.8 (hit, |1-0.8|) and 0.6 (miss, |0-0.6|)
    expect(c.ece).toBeCloseTo((0.2 + 0.6) / 2, 10);
  });
  it('ISO weeks match Python isocalendar', () => {
    expect(isoWeek('2025-01-01')).toBe('2025-W01');
    expect(isoWeek('2024-12-30')).toBe('2025-W01');
    expect(isoWeek('2021-01-03')).toBe('2020-W53');
    expect(isoWeek('2026-12-31')).toBe('2026-W53');
    expect(isoWeek('2025-06-13')).toBe('2025-W24');
  });
});

describe('performance', () => {
  const pr = { down: 0.2, neutral: 0.2, up: 0.6 };
  const row = (iso: string, direction: string, actualClass: string | null): OutcomeRow => ({
    ts: new Date(iso),
    direction,
    modelClass: direction === 'NO_PREDICTION' ? 'UP' : direction,
    actualClass,
    directionCorrect: ['UP', 'DOWN'].includes(direction) && actualClass ? direction === actualClass : null,
    rawProbability: pr,
    calibratedProbability: pr,
  });
  it('coverage, selective accuracy, rolling and Indian-date periods', () => {
    const rows = [
      row('2025-06-12T04:00:00Z', 'UP', 'UP'),
      row('2025-06-12T04:05:00Z', 'DOWN', 'NEUTRAL'), // actual NEUTRAL: the call is wrong
      row('2025-06-12T04:10:00Z', 'NO_PREDICTION', 'DOWN'),
      row('2025-06-12T19:00:00Z', 'UP', 'UP'), // 00:30 IST on 13 June
      row('2025-06-13T09:58:00Z', 'UP', null), // label unavailable
    ];
    const p = performance(rows, [2, 500]);
    expect(p.predictions).toBe(5);
    expect(p.evaluated).toBe(4);
    expect(p.labelUnavailable).toBe(1);
    expect(p.selective.calls).toBe(3);
    expect(p.selective.coverage).toBeCloseTo(0.75, 10);
    expect(p.selective.accuracy).toBeCloseTo(2 / 3, 10);
    expect(p.rolling.last_2).toEqual({ n: 2, accuracy: 0.5 });
    expect(p.fullCoverage.accuracy).toBeCloseTo(0.5, 10);
    expect(p.daily.map((d) => [d.period, d.evaluated, d.calls])).toEqual([
      ['2025-06-12', 3, 2],
      ['2025-06-13', 1, 1],
    ]);
    expect(p.weekly).toHaveLength(1);
    expect(p.monthly[0]).toMatchObject({ period: '2025-06', calls: 3 });
  });
});
