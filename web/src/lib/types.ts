/** Shapes returned by the PulseTrader API (docs/backend.md). Only fields the UI reads are typed. */

export type Role = 'USER' | 'ADMIN';
export type Direction = 'UP' | 'DOWN' | 'NEUTRAL' | 'NO_PREDICTION';
export type ModelStatus = 'EXPERIMENT' | 'CANDIDATE' | 'SHADOW' | 'PRODUCTION' | 'RETIRED' | 'REJECTED';
export type FeedState = 'LIVE' | 'DELAYED' | 'STALE' | 'DISCONNECTED' | 'INVALID' | 'REPLAY';
export type InstrumentType = 'EQUITY' | 'ETF' | 'INDEX' | 'OTHER';

export interface User {
  id: string;
  email: string;
  name: string | null;
  role: Role;
  createdAt: string;
}

export interface Page<T> {
  total: number;
  page: number;
  pageSize: number;
  items: T[];
}

export interface Stock {
  symbol: string;
  name: string | null;
  instrumentType: InstrumentType;
  experimentEligible: boolean;
  inResearchUniverse: boolean;
  firstDate: string | null;
  lastDate: string | null;
  medianDailyTurnover: number | null;
  sector: string | null;
}

export interface LiveStatus {
  state: FeedState;
  provider: string | null;
  mode?: 'LIVE' | 'REPLAY' | null;
  reason: string;
  lastBarClose?: string | null;
  latencyP50Seconds?: number | null;
  observedAt?: string | null;
}

/** Latest validated 1-minute close from the live pipeline (LIVE feed, or a REPLAY of recorded data). */
export interface LivePrice {
  ts: string;
  close: number;
  state: FeedState;
  mode: 'LIVE' | 'REPLAY' | null;
}

export interface Quote {
  tradeDate: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  change: number | null;
  changePct: number | null;
  source: string;
  note: string;
}

export interface RollingAccuracy {
  [window: string]: { n: number; accuracy: number | null };
}

export interface PredictionOutcome {
  actualClass: 'UP' | 'DOWN' | 'NEUTRAL' | null;
  actualPrice: number | null;
  actualReturn: number | null;
  predictionError: number | null;
  directionCorrect: boolean | null;
}

export interface Prediction {
  id: string;
  symbol: string;
  predictionTimestamp: string;
  marketDataTimestamp: string;
  targetTimestamp: string;
  latencyMs: number;
  currentPrice: number | null;
  predictedPrice: number | null;
  predictedReturn: number | null;
  direction: Direction;
  modelClass: Direction;
  abstainReason: string | null;
  rawProbability: Record<'down' | 'neutral' | 'up', number>;
  calibratedProbability: Record<'down' | 'neutral' | 'up', number>;
  confidence: number | null;
  horizonMinutes: number;
  labelThreshold: number;
  modelVersionId: string;
  modelStatus: ModelStatus;
  researchOnly: boolean;
  featureVersion: string;
  dataVersion: string;
  dataQuality: string;
  mode: string;
  createdAt: string;
  outcome?: PredictionOutcome | null;
}

export interface StockDetail {
  stock: Stock;
  quote: Quote | null;
  latestPrediction: Prediction | null;
  recentAccuracy: RollingAccuracy;
  liveStatus: LiveStatus;
  livePrice?: LivePrice | null;
}

export interface DailyBar {
  symbol: string;
  tradeDate: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface MinuteBar {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Indicators {
  symbol: string;
  date: string;
  bar_ts: string;
  availability_ts: string;
  feature_version: string;
  latest: { name: string; label: string; value: number | null }[];
  series: Record<string, { ts: string; value: number | null }[]>;
  parity: { engine: string; warmup_sessions: number };
  regime:
    | { status: 'OK'; index: string; trend: string; volatility: string | null; definition: string }
    | { status: 'DATA_UNAVAILABLE'; reason: string };
}

export interface Period {
  start: string;
  end: string;
  name?: string;
  used?: boolean;
}

export interface ModelVersion {
  id: string;
  modelId: string;
  version: number;
  task: string;
  modelType: string;
  status: ModelStatus;
  datasetVersion: string;
  featureVersion: string;
  labelVersion: string;
  trainingPeriod: Period;
  validationPeriod: Period;
  testPeriod: Period;
  metrics: {
    validation?: { accuracy?: number; balanced_accuracy?: number; mcc?: number; coverage?: number };
  };
  backtestMetrics: { gated_after_costs?: { total_return?: number; sharpe?: number; max_drawdown?: number } };
  calibrationVersion: string | null;
  gates: Record<string, string>;
  accuracyGate: string;
  createdAt: string;
}

export interface Accuracy {
  predictions: number;
  directional: number;
  coverage: number | null;
  evaluated: number;
  modes?: Record<string, number>;
  rolling: RollingAccuracy;
  performance?: Performance;
  note: string | null;
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

/** Live performance over predictions with realised outcomes (API `performance.ts`). */
export interface Performance {
  predictions: number;
  evaluated: number;
  labelUnavailable: number;
  fullCoverage: ClassMetrics & { brier: number | null; ece: number | null };
  calibrated: { brier: number | null; ece: number | null };
  selective: ClassMetrics & { calls: number; coverage: number | null };
  rolling: RollingAccuracy;
  daily: PeriodAccuracy[];
  weekly: PeriodAccuracy[];
  monthly: PeriodAccuracy[];
  window: number;
  truncated: boolean;
}

export interface Ready {
  ready: boolean;
  database: boolean;
  redis: boolean;
  mlService: {
    reachable: boolean;
    ready?: boolean;
    reason?: string | null;
    production_models?: string[];
    loaded_models?: string[];
  };
  marketData: LiveStatus;
}

export interface WatchlistItem {
  id: string;
  symbol: string;
  addedAt: string;
  stock: Stock;
}

export interface Watchlist {
  id: string;
  name: string;
  createdAt: string;
  items: WatchlistItem[];
}

export type AlertCondition = 'PRICE_ABOVE' | 'PRICE_BELOW' | 'PREDICTION_UP' | 'PREDICTION_DOWN';

export interface PriceAlert {
  id: string;
  symbol: string;
  condition: AlertCondition;
  threshold: number | null;
  status: 'ACTIVE' | 'TRIGGERED' | 'DISABLED';
  triggeredAt: string | null;
  createdAt: string;
}

export interface Portfolio {
  id: string;
  name: string;
  cash: number;
  createdAt: string;
}

export interface Position {
  id: string;
  symbol: string;
  quantity: number;
  avgPrice: number;
  price: number | null;
  priceDate: string | null;
}

export interface PortfolioDetail extends Portfolio {
  positions: Position[];
  valuation: {
    cash: number;
    marketValue: number;
    costBasis: number;
    unrealizedPnl: number;
    equity: number;
    unpricedPositions: number;
  };
  pricing: string;
}

export interface ResearchAnswer {
  intent: { kind: string; symbol?: string | null; symbols?: string[] };
  status: 'OK' | 'DATA_UNAVAILABLE' | 'UNSUPPORTED' | string;
  answer: string;
  sources?: string[];
}
