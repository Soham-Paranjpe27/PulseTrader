import { INestApplication } from '@nestjs/common';
import { Test } from '@nestjs/testing';
import { PrismaClient } from '@prisma/client';
import request from 'supertest';
import { startMlStub, MlStub } from './ml-stub';

// Test fixtures (not market data used by any model): two stocks and three daily bars.
const FIXTURE_BARS = [
  {
    symbol: 'RELIANCE',
    tradeDate: new Date('2025-01-02'),
    open: 100,
    high: 102,
    low: 99,
    close: 101,
    volume: 1000,
  },
  {
    symbol: 'RELIANCE',
    tradeDate: new Date('2025-01-03'),
    open: 101,
    high: 104,
    low: 100,
    close: 103,
    volume: 1200,
  },
  { symbol: 'TCS', tradeDate: new Date('2025-01-03'), open: 50, high: 51, low: 49, close: 50, volume: 500 },
];

describe('PulseTrader API (e2e, real PostgreSQL)', () => {
  let app: INestApplication;
  let ml: MlStub;
  let prisma: PrismaClient;

  beforeAll(async () => {
    ml = await startMlStub();
    process.env.DATABASE_URL = process.env.TEST_DATABASE_URL;
    process.env.ML_SERVICE_URL = ml.url;
    process.env.JWT_SECRET = process.env.JWT_SECRET ?? 'e2e-'.padEnd(48, 'x');
    process.env.RATE_LIMIT_PER_MINUTE = '1000';
    process.env.AUTH_RATE_LIMIT_PER_MINUTE = '40';
    process.env.LIVE_STATUS_KEY = `e2e:live:status:${Date.now()}`;
    process.env.MONITOR_INTERVAL_SECONDS = '0'; // checks run on request in tests
    delete process.env.LIVE_INGEST_TOKEN;
    prisma = new PrismaClient({ datasources: { db: { url: process.env.TEST_DATABASE_URL } } });
    await prisma.stock.createMany({
      data: [
        { symbol: 'RELIANCE', instrumentType: 'EQUITY', inResearchUniverse: true, experimentEligible: true },
        { symbol: 'TCS', instrumentType: 'EQUITY', inResearchUniverse: true, experimentEligible: true },
        { symbol: 'NIFTY', instrumentType: 'INDEX' },
      ],
    });
    await prisma.marketData.createMany({ data: FIXTURE_BARS });
    const { AppModule } = await import('../src/app.module');
    const { configureApp } = await import('../src/setup');
    const mod = await Test.createTestingModule({ imports: [AppModule] }).compile();
    app = mod.createNestApplication();
    configureApp(app);
    await app.init();
  });

  afterAll(async () => {
    await app?.close();
    await prisma?.$disconnect();
    ml?.server.close();
  });

  const csrfOf = (res: request.Response): string => {
    const raw = res.headers['set-cookie'] as unknown as string[] | undefined;
    const c = (raw ?? []).find((x) => x.startsWith('csrf_token='));
    if (!c) throw new Error('no csrf cookie');
    return c.split(';')[0].split('=')[1];
  };

  async function login(email: string, password = 'correct horse 123') {
    const agent = request.agent(app.getHttpServer());
    await agent.post('/api/auth/register').send({ email, password }).expect(201);
    const res = await agent.post('/api/auth/login').send({ email, password }).expect(200);
    return { agent, csrf: csrfOf(res), res };
  }

  it('health and readiness', async () => {
    await request(app.getHttpServer()).get('/api/health').expect(200, { status: 'ok' });
    const r = await request(app.getHttpServer()).get('/api/health/ready').expect(200);
    expect(r.body.database).toBe(true);
    expect(r.body.marketData.state).toBe('DISCONNECTED');
    expect(r.headers['x-content-type-options']).toBe('nosniff'); // helmet
  });

  it('registration validates input and hides password hashes', async () => {
    const s = request(app.getHttpServer());
    await s.post('/api/auth/register').send({ email: 'bad', password: 'x' }).expect(400);
    await s.post('/api/auth/register').send({ email: 'a@b.co', password: 'longbutnodigits' }).expect(400);
    await s
      .post('/api/auth/register')
      .send({ email: 'a@b.co', password: 'correct horse 123', role: 'ADMIN' })
      .expect(400);
    const r = await s
      .post('/api/auth/register')
      .send({ email: 'A@B.co', password: 'correct horse 123' })
      .expect(201);
    expect(r.body.user.email).toBe('a@b.co');
    expect(JSON.stringify(r.body)).not.toMatch(/passwordHash|argon2/);
    await s.post('/api/auth/register').send({ email: 'a@b.co', password: 'correct horse 123' }).expect(409);
    const u = await prisma.user.findUniqueOrThrow({ where: { email: 'a@b.co' } });
    expect(u.passwordHash.startsWith('$argon2id$')).toBe(true);
  });

  it('login sets httpOnly cookies; wrong password is rejected; me requires login', async () => {
    const { agent, res } = await login('login@x.co');
    const cookies = (res.headers['set-cookie'] as unknown as string[]).join('\n');
    expect(cookies).toMatch(/access_token=[^;]+;.*HttpOnly/);
    expect(cookies).toMatch(/refresh_token=[^;]+;.*Path=\/api\/auth;.*HttpOnly/);
    expect(cookies).toMatch(/csrf_token=/);
    await agent.get('/api/auth/me').expect(200);
    await request(app.getHttpServer()).get('/api/auth/me').expect(401);
    await request(app.getHttpServer())
      .post('/api/auth/login')
      .send({ email: 'login@x.co', password: 'wrong password 1' })
      .expect(401);
    await request(app.getHttpServer())
      .post('/api/auth/login')
      .send({ email: 'nobody@x.co', password: 'wrong password 1' })
      .expect(401);
  });

  it('refresh rotates the token and detects reuse', async () => {
    const { agent, csrf, res } = await login('refresh@x.co');
    const oldRefresh = (res.headers['set-cookie'] as unknown as string[])
      .find((c) => c.startsWith('refresh_token='))!
      .split(';')[0];
    await agent.post('/api/auth/refresh').expect(403); // no CSRF header
    const r2 = await agent.post('/api/auth/refresh').set('x-csrf-token', csrf).expect(200);
    const csrf2 = csrfOf(r2);
    // replaying the rotated token revokes every session
    await request(app.getHttpServer())
      .post('/api/auth/refresh')
      .set('Cookie', [oldRefresh, `csrf_token=${csrf2}`])
      .set('x-csrf-token', csrf2)
      .expect(401);
    await agent.post('/api/auth/refresh').set('x-csrf-token', csrf2).expect(401);
    const audit = await prisma.auditLog.findFirst({ where: { action: 'auth.refresh_reuse_detected' } });
    expect(audit).not.toBeNull();
  });

  it('stock search and detail', async () => {
    const s = request(app.getHttpServer());
    const r = await s.get('/api/stocks?q=REL').expect(200);
    expect(r.body.items.map((x: { symbol: string }) => x.symbol)).toEqual(['RELIANCE']);
    const t = await s.get('/api/stocks?type=INDEX').expect(200);
    expect(t.body.total).toBe(1);
    await s.get('/api/stocks?pageSize=1000').expect(400);
    const d = await s.get('/api/stocks/reliance').expect(200);
    expect(d.body.quote.close).toBe(103);
    expect(d.body.quote.change).toBe(2);
    expect(d.body.liveStatus.state).toBe('DISCONNECTED');
    await s.get('/api/stocks/NOPE').expect(404);
    const daily = await s.get('/api/market-data/RELIANCE/daily?from=2025-01-03').expect(200);
    expect(daily.body.count).toBe(1);
    await s.get('/api/market-data/RELIANCE/daily?from=yesterday').expect(400);
    // no date: falls back from the latest daily bar to the latest session with minute data
    const ind = await s.get('/api/market-data/RELIANCE/indicators').expect(200);
    expect(ind.body.date).toBe('2025-01-02');
    const miss = await s.get('/api/market-data/RELIANCE/indicators?date=2025-01-03').expect(404);
    expect(miss.body.code).toBe('DATA_UNAVAILABLE');
    await s.get('/api/market-data/RELIANCE/indicators?date=bad').expect(400);
  });

  it('predictions: CSRF, ML errors passed through, stored, listed, research answers from data', async () => {
    const { agent, csrf } = await login('pred@x.co');
    const body = {
      symbol: 'RELIANCE',
      timestamp: '2025-01-06T10:30:00+05:30',
      modelId: 'lightgbm-y_5m_10bp-tuned',
    };
    await agent.post('/api/predictions').send(body).expect(403);
    await request(app.getHttpServer()).post('/api/predictions').send(body).expect(401);
    await agent
      .post('/api/predictions')
      .set('x-csrf-token', csrf)
      .send({ ...body, timestamp: '2025-01-06T10:30:00' })
      .expect(400);
    const noModel = await agent
      .post('/api/predictions')
      .set('x-csrf-token', csrf)
      .send({ symbol: 'RELIANCE', timestamp: body.timestamp })
      .expect(409);
    expect(noModel.body.code).toBe('NO_PRODUCTION_MODEL');
    await agent
      .post('/api/predictions')
      .set('x-csrf-token', csrf)
      .send({ ...body, symbol: 'NOPE' })
      .expect(404);
    const p = await agent.post('/api/predictions').set('x-csrf-token', csrf).send(body).expect(201);
    expect(p.body.direction).toBe('UP');
    expect(p.body.researchOnly).toBe(true);
    expect(p.body.modelVersionId).toBe('lightgbm-y_5m_10bp-tuned@v1');
    const mv = await prisma.modelVersion.findUniqueOrThrow({ where: { id: 'lightgbm-y_5m_10bp-tuned@v1' } });
    expect(mv.status).toBe('CANDIDATE'); // synced from the ML registry on first use
    const list = await request(app.getHttpServer()).get('/api/predictions?symbol=RELIANCE').expect(200);
    expect(list.body.total).toBe(1);
    const acc = await request(app.getHttpServer()).get('/api/predictions/accuracy').expect(200);
    expect(acc.body.evaluated).toBe(0);
    expect(acc.body.note).toMatch(/DATA_UNAVAILABLE/);
    const ask = (q: string) =>
      agent.post('/api/research/ask').set('x-csrf-token', csrf).send({ question: q }).expect(201);
    expect((await ask('What is the latest prediction for RELIANCE?')).body.status).toBe('OK');
    expect((await ask('What is the latest prediction for TCS?')).body.status).toBe('DATA_UNAVAILABLE');
    expect((await ask('Why did the model predict UP for RELIANCE?')).body.status).toBe('DATA_UNAVAILABLE');
    expect((await ask('How accurate has the model been recently?')).body.status).toBe('DATA_UNAVAILABLE');
    expect((await ask('Compare RELIANCE and TCS')).body.status).toBe('OK');
    expect((await ask('tell me something')).body.status).toBe('UNSUPPORTED');
    const models = await request(app.getHttpServer()).get('/api/models/active').expect(200);
    expect(models.body.reason).toMatch(/NO_PRODUCTION_MODEL/);
  });

  it('live ingestion: token auth, replay is never LIVE, predictions and outcomes stored', async () => {
    const http = () => request(app.getHttpServer());
    const status = {
      state: 'LIVE', // a replay claiming LIVE must still be shown as REPLAY
      provider: 'historical-replay',
      mode: 'REPLAY',
      reason: 'recorded data',
      lastBarClose: '2025-06-13T10:16:00+05:30',
      accepted: 10,
      rejected: {},
      observedAt: '2025-06-13T10:16:00+05:30',
      prices: { RELIANCE: { ts: '2025-06-13T10:15:00+05:30', close: 1430.5 } },
    };
    await http().post('/api/live/status').send(status).expect(503); // no token configured
    process.env.LIVE_INGEST_TOKEN = 'i'.repeat(40);
    await http().post('/api/live/status').send(status).expect(403);
    await http().post('/api/live/status').set('x-ingest-token', 'wrong').send(status).expect(403);
    const tok = { 'x-ingest-token': 'i'.repeat(40) };
    const s = await http().post('/api/live/status').set(tok).send(status).expect(200);
    expect(s.body.state).toBe('REPLAY');
    expect((await http().get('/api/market-data/status').expect(200)).body.state).toBe('REPLAY');
    const price = await http().get('/api/market-data/RELIANCE/live').expect(200);
    expect(price.body).toMatchObject({ close: 1430.5, state: 'REPLAY', mode: 'REPLAY' });
    await http().get('/api/market-data/TCS/live').expect(404);
    const pred = {
      prediction_id: '11111111-1111-4111-8111-111111111111',
      symbol: 'RELIANCE',
      prediction_timestamp: '2025-06-13T10:16:00+05:30',
      market_data_timestamp: '2025-06-13T10:15:00+05:30',
      target_timestamp: '2025-06-13T10:20:00+05:30',
      latency_ms: 0.2,
      direction: 'NO_PREDICTION',
      model_class: 'UP',
      abstain_reason: 'LOW_CONFIDENCE',
      raw_probability: { down: 0.3, neutral: 0.3, up: 0.4 },
      calibrated_probability: { down: 0.3, neutral: 0.3, up: 0.4 },
      confidence: 0.4,
      prediction_horizon_minutes: 5,
      label_threshold: 0.001,
      current_price: 1430.5,
      predicted_price: null,
      predicted_return: null,
      model_id: 'lightgbm-y_5m_10bp-tuned',
      model_version: 1,
      model_status: 'CANDIDATE',
      research_only: true,
      feature_version: 'features-v2',
      data_version: 'dataset-v1',
      data_quality: 'REPLAY_VALIDATED',
      mode: 'REPLAY',
      feed_state: 'REPLAY',
    };
    await http()
      .post('/api/live/ingest')
      .set(tok)
      .send({ predictions: [{ ...pred, direction: 'MAYBE' }] })
      .expect(400);
    const r = await http()
      .post('/api/live/ingest')
      .set(tok)
      .send({ predictions: [pred] })
      .expect(200);
    expect(r.body).toEqual({ received: 1, stored: 1 });
    const again = await http()
      .post('/api/live/ingest')
      .set(tok)
      .send({ predictions: [pred] })
      .expect(200);
    expect(again.body.stored).toBe(0); // idempotent on prediction_id
    const row = await prisma.prediction.findUniqueOrThrow({ where: { id: pred.prediction_id } });
    expect(row.mode).toBe('REPLAY');
    expect(row.requestedById).toBeNull();

    // Phase 18: realised outcomes after the horizon, and live performance per mode
    const call = { ...pred, prediction_id: '22222222-2222-4222-8222-222222222222', direction: 'UP' };
    await http()
      .post('/api/live/ingest')
      .set(tok)
      .send({ predictions: [call] })
      .expect(200);
    const outcome = (id: string, cls: string | null, ok: boolean | null) => ({
      prediction_id: id,
      actual_price: 1432.0,
      actual_return: 0.00105,
      actual_class: cls,
      prediction_error: null,
      direction_correct: ok,
    });
    await http()
      .post('/api/live/outcomes')
      .send({ outcomes: [outcome(call.prediction_id, 'UP', true)] })
      .expect(403);
    await http()
      .post('/api/live/outcomes')
      .set(tok)
      .send({ outcomes: [outcome(call.prediction_id, null, true)] }) // correctness without a label
      .expect(400);
    const o = await http()
      .post('/api/live/outcomes')
      .set(tok)
      .send({
        outcomes: [
          outcome(pred.prediction_id, 'UP', null), // abstention: no correctness
          outcome(call.prediction_id, 'UP', true),
          outcome('33333333-3333-4333-8333-333333333333', 'DOWN', false), // unknown prediction
        ],
      })
      .expect(200);
    expect(o.body).toEqual({ received: 3, stored: 2, unknown: 1 });
    const acc = await http().get('/api/predictions/accuracy?mode=REPLAY&symbol=RELIANCE').expect(200);
    expect(acc.body).toMatchObject({ predictions: 2, directional: 1, evaluated: 1, note: null });
    expect(acc.body.performance.selective).toMatchObject({ calls: 1, coverage: 0.5, accuracy: 1 });
    expect(acc.body.performance.fullCoverage).toMatchObject({ n: 2, accuracy: 1 });
    expect(acc.body.performance.daily).toEqual([
      { period: '2025-06-13', evaluated: 2, calls: 1, coverage: 0.5, accuracy: 1 },
    ]);
    expect(acc.body.rolling.last_20).toEqual({ n: 1, accuracy: 1 });
    expect((await http().get('/api/predictions/accuracy?mode=LIVE').expect(200)).body.evaluated).toBe(0);
    await http().get('/api/predictions/accuracy?mode=MAGIC').expect(400);
    const listed = await http().get('/api/predictions?mode=REPLAY&symbol=RELIANCE').expect(200);
    expect(listed.body.total).toBe(2);
    expect(listed.body.items.find((x: { id: string }) => x.id === call.prediction_id).outcome).toMatchObject({
      actualClass: 'UP',
      directionCorrect: true,
    });
    await prisma.prediction.deleteMany({ where: { id: { in: [pred.prediction_id, call.prediction_id] } } });
  });

  it('monitoring: drift reports raise and clear alerts; health summary; admin-only resolve', async () => {
    const http = () => request(app.getHttpServer());
    process.env.LIVE_INGEST_TOKEN = 'i'.repeat(40);
    const tok = { 'x-ingest-token': 'i'.repeat(40) };
    const empty = await http().get('/api/monitoring').expect(200);
    expect(empty.body.components.database).toBe(true);
    expect(empty.body.components.mlService.reachable).toBe(true);
    expect(empty.body.drift.status).toBe('DATA_UNAVAILABLE');
    expect(empty.body.components.marketData.state).toBe('REPLAY'); // set by the live ingestion test
    expect(empty.body.components.marketData.marketOpen).toEqual(expect.any(Boolean));
    const report = (status: string, reasons: string[]) => ({
      model: 'lightgbm-y_5m_10bp-tuned@v1',
      mode: 'REPLAY',
      status,
      reasons,
      window: { kind: 'session', start: '2025-01-20', end: '2025-01-20' },
      components: { accuracy: { status: reasons.length ? 'DRIFT' : 'OK' } },
      latency: { inference_ms_p50: 0.4 },
    });
    await http()
      .post('/api/live/monitoring')
      .send({ reports: [report('OK', [])] })
      .expect(403);
    await http()
      .post('/api/live/monitoring')
      .set(tok)
      .send({ reports: [{ ...report('OK', []), status: 'FINE' }] })
      .expect(400);
    const drift = report('MODEL_DRIFT_DETECTED', ['accuracy DRIFT']);
    await http()
      .post('/api/live/monitoring')
      .set(tok)
      .send({ reports: [drift] })
      .expect(200, { stored: 1 });
    await http()
      .post('/api/live/monitoring')
      .set(tok)
      .send({ reports: [drift] })
      .expect(200);
    const s = await http().get('/api/monitoring').expect(200);
    expect(s.body.status).toBe('CRITICAL');
    expect(s.body.drift.status).toBe('MODEL_DRIFT_DETECTED');
    const alert = s.body.alerts.find((a: { kind: string }) => a.kind === 'MODEL_DRIFT_DETECTED');
    expect(alert).toMatchObject({ severity: 'CRITICAL', count: 2, open: true });
    expect(alert.message).toMatch(/not replaced automatically/);
    await http().get('/api/monitoring/alerts').expect(401); // login required
    const u = await login('mon@x.co');
    expect((await u.agent.get('/api/monitoring/alerts?open=true').expect(200)).body).toHaveLength(1);
    expect((await u.agent.get('/api/monitoring/reports').expect(200)).body).toHaveLength(2);
    await u.agent.post(`/api/monitoring/alerts/${alert.id}/resolve`).set('x-csrf-token', u.csrf).expect(403);
    // a healthy report for the same model, mode and window length clears the alert automatically
    await http()
      .post('/api/live/monitoring')
      .set(tok)
      .send({ reports: [report('OK', [])] })
      .expect(200);
    const after = await http().get('/api/monitoring').expect(200);
    expect(after.body.alerts.filter((a: { kind: string }) => a.kind === 'MODEL_DRIFT_DETECTED')).toHaveLength(
      0,
    );
    expect(after.body.drift.status).toBe('OK');
    const closed = await prisma.systemAlert.findUniqueOrThrow({ where: { id: alert.id } });
    expect(closed).toMatchObject({ open: false, resolvedBy: 'auto' });
    // admins can resolve by hand
    await http()
      .post('/api/live/monitoring')
      .set(tok)
      .send({ reports: [drift] })
      .expect(200);
    const again = await prisma.systemAlert.findFirstOrThrow({
      where: { kind: 'MODEL_DRIFT_DETECTED', open: true },
    });
    await prisma.user.update({ where: { email: 'mon@x.co' }, data: { role: 'ADMIN' } });
    const adminRes = await u.agent
      .post('/api/auth/login')
      .send({ email: 'mon@x.co', password: 'correct horse 123' })
      .expect(200);
    const r = await u.agent
      .post(`/api/monitoring/alerts/${again.id}/resolve`)
      .set('x-csrf-token', csrfOf(adminRes))
      .expect(200);
    expect(r.body.open).toBe(false);
    // request latency is recorded per route pattern
    const lat = (await http().get('/api/monitoring').expect(200)).body.components.api;
    expect(lat.requests).toBeGreaterThan(0);
    expect(lat.slowestRoutes.map((x: { route: string }) => x.route)).toContain('POST /api/live/monitoring');
    await prisma.monitoringReport.deleteMany({});
    await prisma.systemAlert.deleteMany({});
  });

  it('watchlists are private to their owner', async () => {
    const a = await login('wa@x.co');
    const b = await login('wb@x.co');
    const w = await a.agent
      .post('/api/watchlists')
      .set('x-csrf-token', a.csrf)
      .send({ name: 'Banks' })
      .expect(201);
    await a.agent
      .post(`/api/watchlists/${w.body.id}/items`)
      .set('x-csrf-token', a.csrf)
      .send({ symbol: 'reliance' })
      .expect(201);
    await a.agent
      .post(`/api/watchlists/${w.body.id}/items`)
      .set('x-csrf-token', a.csrf)
      .send({ symbol: 'NOPE' })
      .expect(404);
    const list = await a.agent.get('/api/watchlists').expect(200);
    expect(list.body[0].items[0].symbol).toBe('RELIANCE');
    expect((await b.agent.get('/api/watchlists').expect(200)).body).toEqual([]);
    await b.agent
      .post(`/api/watchlists/${w.body.id}/items`)
      .set('x-csrf-token', b.csrf)
      .send({ symbol: 'TCS' })
      .expect(404);
    await b.agent.delete(`/api/watchlists/${w.body.id}`).set('x-csrf-token', b.csrf).expect(404);
    await a.agent
      .delete(`/api/watchlists/${w.body.id}/items/RELIANCE`)
      .set('x-csrf-token', a.csrf)
      .expect(200);
  });

  it('alerts: create, validate, evaluate (admin only), disable', async () => {
    const u = await login('alert@x.co');
    await u.agent
      .post('/api/alerts')
      .set('x-csrf-token', u.csrf)
      .send({ symbol: 'RELIANCE', condition: 'PRICE_ABOVE' })
      .expect(400);
    const a = await u.agent
      .post('/api/alerts')
      .set('x-csrf-token', u.csrf)
      .send({ symbol: 'RELIANCE', condition: 'PRICE_ABOVE', threshold: 102 })
      .expect(201);
    await u.agent
      .post('/api/alerts')
      .set('x-csrf-token', u.csrf)
      .send({ symbol: 'TCS', condition: 'PRICE_BELOW', threshold: 10 })
      .expect(201);
    await u.agent.post('/api/admin/alerts/evaluate').set('x-csrf-token', u.csrf).expect(403);
    await prisma.user.update({ where: { email: 'alert@x.co' }, data: { role: 'ADMIN' } });
    // role is read from the access token, so log in again to get an ADMIN token
    const adminRes = await u.agent
      .post('/api/auth/login')
      .send({ email: 'alert@x.co', password: 'correct horse 123' })
      .expect(200);
    const csrf = csrfOf(adminRes);
    const ev = await u.agent.post('/api/admin/alerts/evaluate').set('x-csrf-token', csrf).expect(201);
    expect(ev.body.triggered).toBeGreaterThanOrEqual(1);
    const mine = await u.agent.get('/api/alerts').expect(200);
    const fired = mine.body.find((x: { id: string }) => x.id === a.body.id);
    expect(fired.status).toBe('TRIGGERED');
    expect(mine.body.find((x: { symbol: string }) => x.symbol === 'TCS').status).toBe('ACTIVE');
    await u.agent
      .patch(`/api/alerts/${a.body.id}`)
      .set('x-csrf-token', csrf)
      .send({ status: 'DISABLED' })
      .expect(200);
    const audit = await u.agent.get('/api/admin/audit').expect(200);
    expect(audit.body.items.some((x: { action: string }) => x.action === 'admin.evaluate_alerts')).toBe(true);
  });

  it('paper portfolio trades at the latest stored close', async () => {
    const u = await login('pf@x.co');
    const p = await u.agent
      .post('/api/portfolios')
      .set('x-csrf-token', u.csrf)
      .send({ name: 'Paper', cash: 1000 })
      .expect(201);
    const t = await u.agent
      .post(`/api/portfolios/${p.body.id}/trades`)
      .set('x-csrf-token', u.csrf)
      .send({ symbol: 'RELIANCE', side: 'BUY', quantity: 5 })
      .expect(201);
    expect(t.body.price).toBe(103);
    expect(t.body.portfolio.cash).toBe(1000 - 515);
    await u.agent
      .post(`/api/portfolios/${p.body.id}/trades`)
      .set('x-csrf-token', u.csrf)
      .send({ symbol: 'RELIANCE', side: 'BUY', quantity: 50 })
      .expect(400);
    await u.agent
      .post(`/api/portfolios/${p.body.id}/trades`)
      .set('x-csrf-token', u.csrf)
      .send({ symbol: 'TCS', side: 'SELL', quantity: 1 })
      .expect(400);
    const g = await u.agent.get(`/api/portfolios/${p.body.id}`).expect(200);
    expect(g.body.valuation.equity).toBeCloseTo(1000);
    const other = await login('pf2@x.co');
    await other.agent.get(`/api/portfolios/${p.body.id}`).expect(404);
  });

  it('concurrent paper trades neither lose updates nor oversell', async () => {
    const u = await login('race@x.co');
    const p = await u.agent
      .post('/api/portfolios')
      .set('x-csrf-token', u.csrf)
      .send({ name: 'Race', cash: 10000 })
      .expect(201);
    const trade = (side: 'BUY' | 'SELL', quantity: number) =>
      u.agent
        .post(`/api/portfolios/${p.body.id}/trades`)
        .set('x-csrf-token', u.csrf)
        .send({ symbol: 'RELIANCE', side, quantity });
    const buys = await Promise.all(Array.from({ length: 8 }, () => trade('BUY', 1)));
    expect(buys.map((r) => r.status)).toEqual(Array(8).fill(201));
    let g = await u.agent.get(`/api/portfolios/${p.body.id}`).expect(200);
    expect(g.body.cash).toBeCloseTo(10000 - 8 * 103);
    expect(g.body.positions[0].quantity).toBe(8);
    const sells = await Promise.all(Array.from({ length: 5 }, () => trade('SELL', 4)));
    expect(sells.filter((r) => r.status === 201)).toHaveLength(2);
    expect(sells.filter((r) => r.status === 400)).toHaveLength(3);
    g = await u.agent.get(`/api/portfolios/${p.body.id}`).expect(200);
    expect(g.body.positions).toHaveLength(0);
    expect(g.body.cash).toBeCloseTo(10000);
  });

  it('concurrent duplicates hit unique constraints as 409, never 500', async () => {
    const s = request(app.getHttpServer());
    const regs = await Promise.all(
      Array.from({ length: 5 }, () =>
        s.post('/api/auth/register').send({ email: 'dup@x.co', password: 'correct horse 123' }),
      ),
    );
    expect(regs.filter((r) => r.status === 201)).toHaveLength(1);
    expect(regs.filter((r) => r.status === 409)).toHaveLength(4);
    const u = await login('dupw@x.co');
    const w = await u.agent
      .post('/api/watchlists')
      .set('x-csrf-token', u.csrf)
      .send({ name: 'Dup' })
      .expect(201);
    const adds = await Promise.all(
      Array.from({ length: 5 }, () =>
        u.agent
          .post(`/api/watchlists/${w.body.id}/items`)
          .set('x-csrf-token', u.csrf)
          .send({ symbol: 'TCS' }),
      ),
    );
    expect(adds.every((r) => r.status === 201 || r.status === 409)).toBe(true);
    const names = await Promise.all(
      Array.from({ length: 3 }, () =>
        u.agent.post('/api/portfolios').set('x-csrf-token', u.csrf).send({ name: 'Same', cash: 1 }),
      ),
    );
    expect(names.filter((r) => r.status === 201)).toHaveLength(1);
    expect(names.filter((r) => r.status === 409)).toHaveLength(2);
    const list = await u.agent.get('/api/watchlists').expect(200);
    expect(list.body[0].items).toHaveLength(1);
  });

  it('logout revokes the session', async () => {
    const { agent, csrf } = await login('bye@x.co');
    await agent.post('/api/auth/logout').set('x-csrf-token', csrf).expect(200);
    await agent.get('/api/auth/me').expect(401);
    await agent.post('/api/auth/refresh').set('x-csrf-token', csrf).expect(403); // csrf cookie cleared too
    const s = await prisma.session.findMany({ where: { user: { email: 'bye@x.co' } } });
    expect(s.every((x) => x.revokedAt !== null)).toBe(true);
  });

  it('swagger document is served', async () => {
    const r = await request(app.getHttpServer()).get('/api/docs-json').expect(200);
    expect(Object.keys(r.body.paths)).toEqual(
      expect.arrayContaining(['/api/auth/login', '/api/predictions', '/api/research/ask']),
    );
  });

  it('rate-limits login attempts', async () => {
    const s = request(app.getHttpServer());
    const codes: number[] = [];
    for (let i = 0; i < 45; i++) {
      codes.push(
        (await s.post('/api/auth/login').send({ email: 'rl@x.co', password: 'wrong password 1' })).status,
      );
    }
    expect(codes).toContain(429);
  });
});
