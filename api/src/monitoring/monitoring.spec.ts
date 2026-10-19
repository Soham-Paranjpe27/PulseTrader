import { LatencyRecorder, quantile } from './latency';
import { marketOpen, validReport } from './monitoring.service';

describe('latency', () => {
  it('quantiles and a sliding window per route', () => {
    expect(quantile([], 0.5)).toBeNull();
    expect(quantile([1, 2, 3, 4], 0.5)).toBe(3);
    const r = new LatencyRecorder();
    const now = Date.now();
    r.record('GET /a', 10, 200, now - 10 * 60_000); // outside the 5-minute window
    for (let i = 1; i <= 100; i++) r.record('GET /b', i, i === 100 ? 503 : 200, now);
    const s = r.summary(5 * 60_000, now);
    expect(s.requests).toBe(100);
    expect(s.errors5xx).toBe(1);
    expect(s.p50).toBe(51);
    expect(s.p95).toBe(96);
    expect(s.slowestRoutes).toEqual([expect.objectContaining({ route: 'GET /b', requests: 100 })]);
  });
});

describe('monitoring helpers', () => {
  it('market hours are NSE cash hours in IST, weekdays only', () => {
    expect(marketOpen(new Date('2025-06-13T04:00:00Z'))).toBe(true); // Fri 09:30 IST
    expect(marketOpen(new Date('2025-06-13T03:40:00Z'))).toBe(false); // 09:10 IST
    expect(marketOpen(new Date('2025-06-13T10:05:00Z'))).toBe(false); // 15:35 IST
    expect(marketOpen(new Date('2025-06-14T05:00:00Z'))).toBe(false); // Saturday
  });
  it('validates drift reports', () => {
    const ok = {
      model: 'm@v1',
      mode: 'LIVE',
      status: 'WARN',
      reasons: ['feature WARN'],
      window: { kind: 'session', start: '2025-06-13', end: '2025-06-13' },
      components: {},
    };
    expect(validReport(ok)).toBe(true);
    expect(validReport({ ...ok, mode: 'HISTORICAL' })).toBe(false);
    expect(validReport({ ...ok, status: 'GOOD' })).toBe(false);
    expect(validReport({ ...ok, window: { ...ok.window, end: 'yesterday' } })).toBe(false);
    expect(validReport({ ...ok, reasons: [1] })).toBe(false);
  });
});
