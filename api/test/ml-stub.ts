import { createServer, IncomingMessage, Server, ServerResponse } from 'node:http';
import { AddressInfo } from 'node:net';

/**
 * TEST-ONLY stand-in for the Python ML service HTTP API, so backend e2e tests run without model
 * artifacts. The real service is exercised by the Python tests and the Phase 14 parity check.
 */
export interface MlStub {
  url: string;
  server: Server;
  requests: { path: string; body: unknown }[];
}

const MODEL = {
  model_id: 'lightgbm-y_5m_10bp-tuned',
  version: 1,
  status: 'CANDIDATE',
  task: 'y_5m_10bp',
  created_at: '2026-10-19T07:32:32Z',
  accuracy_gate: 'NOT VERIFIED',
  validation: { accuracy: 0.48, balanced_accuracy: 0.431, mcc: 0.168, coverage: 1 },
  backtest_gated_after_costs: { total_return: -0.344, sharpe: -11.35, max_drawdown: -0.345 },
  gates: { no_leakage: 'PASSED', backtest_passed: 'FAILED', test_passed: 'NOT_RUN' },
  model_type: 'lightgbm',
  dataset_version: 'dataset-test',
  feature_version: 'features-v2',
  label_version: 'labels-v1',
  training_period: { start: '2022-01-03', end: '2024-11-04' },
  validation_period: { start: '2024-11-05', end: '2025-06-13' },
  test_period: { start: '2025-06-16', end: '2026-01-21', used: false },
  hyperparameters: { learning_rate: 0.03 },
  calibration_version: 'calibrate-v1:isotonic',
  artifact_path: 'artifacts/x/v1',
  history: [],
};

function body(req: IncomingMessage): Promise<unknown> {
  return new Promise((resolve, reject) => {
    let s = '';
    req.on('data', (c: Buffer) => (s += c.toString()));
    req.on('end', () => resolve(s ? JSON.parse(s) : null));
    req.on('error', reject);
  });
}

function prediction(item: { symbol: string; timestamp: string; model_id?: string }, i: number) {
  const ts = new Date(item.timestamp);
  const up = i % 2 === 0;
  return {
    prediction_id: `00000000-0000-4000-8000-${String(Date.now() % 1e6).padStart(6, '0')}${String(i).padStart(6, '0')}`,
    symbol: item.symbol,
    prediction_timestamp: new Date(ts.getTime() + 60_000).toISOString(),
    market_data_timestamp: ts.toISOString(),
    target_timestamp: new Date(ts.getTime() + 300_000).toISOString(),
    latency_ms: 1.2,
    direction: up ? 'UP' : 'NO_PREDICTION',
    model_class: 'UP',
    abstain_reason: up ? null : 'LOW_CONFIDENCE',
    raw_probability: { down: 0.2, neutral: 0.2, up: 0.6 },
    calibrated_probability: { down: 0.25, neutral: 0.3, up: 0.45 },
    confidence: 0.6,
    prediction_horizon_minutes: 5,
    label_threshold: 0.001,
    current_price: null,
    predicted_price: null,
    predicted_return: null,
    model_id: MODEL.model_id,
    model_version: 1,
    model_status: 'CANDIDATE',
    research_only: true,
    feature_version: 'features-v2',
    data_version: 'dataset-test',
    data_quality: 'VALIDATED_HISTORICAL:validation',
  };
}

export async function startMlStub(): Promise<MlStub> {
  const requests: MlStub['requests'] = [];
  const server = createServer((req: IncomingMessage, res: ServerResponse) => {
    void (async () => {
      const b = await body(req);
      const path = req.url ?? '/';
      requests.push({ path, body: b });
      const send = (code: number, payload: unknown) => {
        res.writeHead(code, { 'content-type': 'application/json' });
        res.end(JSON.stringify(payload));
      };
      if (path === '/predict/batch') {
        const items = (b as { items: { symbol: string; timestamp: string; model_id?: string }[] }).items;
        if (items.some((x) => !x.model_id)) {
          return send(409, { detail: { code: 'NO_PRODUCTION_MODEL', message: 'NO_PRODUCTION_MODEL: none' } });
        }
        return send(200, { count: items.length, predictions: items.map(prediction) });
      }
      if (path === '/models') return send(200, { models: [MODEL] });
      if (path === '/features') {
        return send(200, {
          models: [
            {
              model: 'x@v1',
              feature_version: 'features-v2',
              count: 2,
              features: [{ name: 'ret_1' }, { name: 'ret_5' }],
            },
          ],
        });
      }
      if (path === '/ready') return send(200, { ready: true, reason: 'NO_PRODUCTION_MODEL' });
      if (path.startsWith('/bars/'))
        return send(200, { symbol: 'RELIANCE', date: '2025-01-06', bars: [{ ts: 'x', close: 1 }] });
      return send(404, { detail: { code: 'NOT_FOUND', message: path } });
    })();
  });
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', r));
  const port = (server.address() as AddressInfo).port;
  return { url: `http://127.0.0.1:${port}`, server, requests };
}
