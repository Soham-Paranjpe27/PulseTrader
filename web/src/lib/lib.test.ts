import { expect, test } from '@playwright/test';
import { ApiError, qs, readCookie, toApiError } from './api';
import { buildCsp } from './csp';
import { dailyCandles, IST_OFFSET_SECONDS, lookbackStart, minuteCandles } from './chart';
import { codeLabel, compact, day, inr, istTime, num, pct } from './format';
import { buildUpstreamUrl, forwardRequestHeaders, forwardResponseHeaders } from './proxy';
import { safeNext } from './redirect';
import { alertSchema, istTimestamp, predictionSchema, registerSchema, tradeSchema } from './schemas';

test.describe('proxy', () => {
  test('builds upstream URLs only inside /api', () => {
    expect(buildUpstreamUrl('http://api:3001/', ['stocks', 'M&M'], '?q=1')).toBe(
      'http://api:3001/api/stocks/M%26M?q=1',
    );
    expect(buildUpstreamUrl('http://api:3001', ['market-data', 'NIFTY 50', 'daily'], '')).toBe(
      'http://api:3001/api/market-data/NIFTY%2050/daily',
    );
    expect(buildUpstreamUrl('http://x', ['..', 'admin'], '')).toBeNull();
    expect(buildUpstreamUrl('http://x', ['a/b'], '')).toBeNull();
    expect(buildUpstreamUrl('http://x', [], '')).toBeNull();
    expect(buildUpstreamUrl('http://x', ['a\nb'], '')).toBeNull();
  });

  test('forwards only allow-listed headers and every set-cookie', () => {
    const inH = new Headers({
      cookie: 'a=1',
      'x-csrf-token': 't',
      host: 'evil',
      authorization: 'x',
      'x-forwarded-for': '1.2.3.4',
    });
    const out = forwardRequestHeaders(inH);
    expect(out.get('cookie')).toBe('a=1');
    expect(out.get('x-csrf-token')).toBe('t');
    expect(out.get('host')).toBeNull();
    expect(out.get('authorization')).toBeNull();
    expect(out.get('x-forwarded-for')).toBe('1.2.3.4');
    const up = new Headers({ 'content-type': 'text/event-stream', server: 'x' });
    up.append('set-cookie', 'access_token=a; HttpOnly');
    up.append('set-cookie', 'csrf_token=b');
    const res = forwardResponseHeaders(up);
    expect(res.getSetCookie()).toEqual(['access_token=a; HttpOnly', 'csrf_token=b']);
    expect(res.get('server')).toBeNull();
    expect(res.get('cache-control')).toBe('no-cache, no-transform');
  });
});

test.describe('api client helpers', () => {
  test('maps error bodies to codes', () => {
    const a = toApiError(403, { code: 'TEST_PERIOD_LOCKED', message: 'locked' });
    expect(a).toBeInstanceOf(ApiError);
    expect([a.status, a.code, a.message]).toEqual([403, 'TEST_PERIOD_LOCKED', 'locked']);
    expect(toApiError(400, { message: ['a', 'b'], error: 'Bad Request' }).message).toBe('a; b');
    expect(toApiError(401, { message: 'login required' }).code).toBe('UNAUTHORIZED');
    expect(toApiError(502, '').code).toBe('HTTP_502');
    expect(toApiError(429, { message: 'ThrottlerException: Too Many Requests' }).code).toBe('RATE_LIMITED');
  });

  test('reads cookies and builds query strings', () => {
    expect(readCookie('a=1; csrf_token=x%3Dy; b=2', 'csrf_token')).toBe('x=y');
    expect(readCookie('a=1', 'csrf_token')).toBeNull();
    expect(qs({ q: 'REL', page: 1, x: undefined, y: '' })).toBe('?q=REL&page=1');
    expect(qs({})).toBe('');
  });

  test('post-login redirect stays on this site', () => {
    expect(safeNext('/stocks/TCS')).toBe('/stocks/TCS');
    expect(safeNext('//evil.example')).toBe('/dashboard');
    expect(safeNext('https://evil.example')).toBe('/dashboard');
    expect(safeNext('/\\evil.example')).toBe('/dashboard');
    expect(safeNext(null)).toBe('/dashboard');
  });
});

test.describe('schemas', () => {
  test('register mirrors the API password rule', () => {
    const ok = { email: 'a@b.co', password: 'longpassword1', confirm: 'longpassword1' };
    expect(registerSchema.safeParse(ok).success).toBe(true);
    expect(registerSchema.safeParse({ ...ok, password: 'short1', confirm: 'short1' }).success).toBe(false);
    expect(
      registerSchema.safeParse({ ...ok, password: 'nodigitsatall', confirm: 'nodigitsatall' }).success,
    ).toBe(false);
    expect(registerSchema.safeParse({ ...ok, confirm: 'other' }).success).toBe(false);
  });

  test('price alerts need a threshold; prediction alerts do not', () => {
    expect(alertSchema.safeParse({ symbol: 'TCS', condition: 'PRICE_ABOVE' }).success).toBe(false);
    expect(
      alertSchema.safeParse({ symbol: 'TCS', condition: 'PRICE_ABOVE', threshold: '3500' }).success,
    ).toBe(true);
    expect(alertSchema.safeParse({ symbol: 'TCS', condition: 'PREDICTION_UP' }).success).toBe(true);
    expect(alertSchema.safeParse({ symbol: 'bad/sym', condition: 'PREDICTION_UP' }).success).toBe(false);
  });

  test('trades and predictions', () => {
    expect(tradeSchema.parse({ symbol: 'INFY', side: 'BUY', quantity: '5' }).quantity).toBe(5);
    expect(tradeSchema.safeParse({ symbol: 'INFY', side: 'BUY', quantity: 0 }).success).toBe(false);
    const p = { modelId: 'm@v1', date: '2025-06-13', time: '10:30' };
    expect(predictionSchema.safeParse(p).success).toBe(true);
    expect(predictionSchema.safeParse({ ...p, time: '09:00' }).success).toBe(false);
    expect(predictionSchema.safeParse({ ...p, time: '15:30' }).success).toBe(false);
    expect(istTimestamp('2025-06-13', '10:30')).toBe('2025-06-13T10:30:00+05:30');
  });
});

test.describe('chart data', () => {
  test('daily candles are sorted, deduplicated and dated', () => {
    const b = (d: string, c: number) => ({
      symbol: 'X',
      tradeDate: `${d}T00:00:00.000Z`,
      open: 1,
      high: 2,
      low: 0.5,
      close: c,
      volume: 10,
    });
    const { candles, volume } = dailyCandles([
      b('2025-01-03', 1.5),
      b('2025-01-02', 0.8),
      b('2025-01-02', 0.8),
    ]);
    expect(candles.map((c) => c.time)).toEqual(['2025-01-02', '2025-01-03']);
    expect(volume.map((v) => v.up)).toEqual([false, true]);
  });

  test('minute candles are shifted to IST wall-clock seconds', () => {
    const { candles } = minuteCandles([
      { ts: '2025-01-06T09:15:00+05:30', open: 1, high: 1, low: 1, close: 1, volume: 1 },
    ]);
    // 09:15 IST = 03:45 UTC; shifted so the chart's UTC axis reads 09:15
    expect(candles[0]!.time).toBe(Date.UTC(2025, 0, 6, 3, 45) / 1000 + IST_OFFSET_SECONDS);
    expect(new Date((candles[0]!.time as number) * 1000).toISOString().slice(11, 16)).toBe('09:15');
  });

  test('lookback start', () => {
    expect(lookbackStart('2026-01-22', 365)).toBe('2025-01-22');
  });
});

test.describe('format', () => {
  test('missing values render as a dash, never zero', () => {
    for (const f of [num, inr, pct, compact]) expect(f(null)).toBe('–');
    expect(pct(Number.NaN)).toBe('–');
    expect(day(null)).toBe('–');
    expect(istTime('garbage')).toBe('–');
  });

  test('numbers, percentages and IST times', () => {
    expect(pct(0.4806)).toBe('48.1%');
    expect(pct(0.012, 1, true)).toBe('+1.2%');
    expect(inr(1234.5)).toBe('₹1,234.50');
    expect(compact(1.82e10)).toBe('1820.00 Cr');
    expect(istTime('2025-01-06T05:00:00.000Z')).toBe('06 Jan 2025, 10:30 IST');
    expect(codeLabel('TEST_PERIOD_LOCKED')).toBe('Test period locked');
  });
});

test.describe('csp', () => {
  test('scripts need the nonce; no inline or eval outside development', () => {
    const p = buildCsp('abc');
    expect(p).toContain("script-src 'self' 'nonce-abc' 'strict-dynamic'");
    expect(p).not.toMatch(/script-src[^;]*'unsafe-(inline|eval)'/);
    expect(p).toContain("frame-ancestors 'none'");
    expect(buildCsp('abc', true)).toContain("'unsafe-eval'");
  });
});
