-- CreateEnum
CREATE TYPE "Role" AS ENUM ('USER', 'ADMIN');

-- CreateEnum
CREATE TYPE "InstrumentType" AS ENUM ('EQUITY', 'ETF', 'INDEX', 'OTHER');

-- CreateEnum
CREATE TYPE "Direction" AS ENUM ('UP', 'DOWN', 'NEUTRAL', 'NO_PREDICTION');

-- CreateEnum
CREATE TYPE "ModelStatus" AS ENUM ('EXPERIMENT', 'CANDIDATE', 'SHADOW', 'PRODUCTION', 'RETIRED', 'REJECTED');

-- CreateEnum
CREATE TYPE "AlertCondition" AS ENUM ('PRICE_ABOVE', 'PRICE_BELOW', 'PREDICTION_UP', 'PREDICTION_DOWN');

-- CreateEnum
CREATE TYPE "AlertStatus" AS ENUM ('ACTIVE', 'TRIGGERED', 'DISABLED');

-- CreateTable
CREATE TABLE "User" (
    "id" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "passwordHash" TEXT NOT NULL,
    "name" TEXT,
    "role" "Role" NOT NULL DEFAULT 'USER',
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "User_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Session" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "refreshTokenHash" TEXT NOT NULL,
    "userAgent" TEXT,
    "ip" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "expiresAt" TIMESTAMP(3) NOT NULL,
    "revokedAt" TIMESTAMP(3),

    CONSTRAINT "Session_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Stock" (
    "symbol" TEXT NOT NULL,
    "name" TEXT,
    "instrumentType" "InstrumentType" NOT NULL,
    "experimentEligible" BOOLEAN NOT NULL DEFAULT false,
    "inResearchUniverse" BOOLEAN NOT NULL DEFAULT false,
    "firstDate" DATE,
    "lastDate" DATE,
    "medianDailyTurnover" DOUBLE PRECISION,
    "sector" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Stock_pkey" PRIMARY KEY ("symbol")
);

-- CreateTable
CREATE TABLE "SymbolHistory" (
    "id" SERIAL NOT NULL,
    "symbol" TEXT NOT NULL,
    "oldSymbol" TEXT,
    "validFrom" DATE,
    "validTo" DATE,
    "note" TEXT,

    CONSTRAINT "SymbolHistory_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "MarketData" (
    "symbol" TEXT NOT NULL,
    "tradeDate" DATE NOT NULL,
    "open" DOUBLE PRECISION NOT NULL,
    "high" DOUBLE PRECISION NOT NULL,
    "low" DOUBLE PRECISION NOT NULL,
    "close" DOUBLE PRECISION NOT NULL,
    "volume" DOUBLE PRECISION NOT NULL,
    "source" TEXT NOT NULL DEFAULT 'hf:xxparthparekhxx/indian-stock-market-minute-data',

    CONSTRAINT "MarketData_pkey" PRIMARY KEY ("symbol","tradeDate")
);

-- CreateTable
CREATE TABLE "ModelVersion" (
    "id" TEXT NOT NULL,
    "modelId" TEXT NOT NULL,
    "version" INTEGER NOT NULL,
    "task" TEXT NOT NULL,
    "modelType" TEXT NOT NULL,
    "status" "ModelStatus" NOT NULL,
    "datasetVersion" TEXT NOT NULL,
    "featureVersion" TEXT NOT NULL,
    "labelVersion" TEXT NOT NULL,
    "trainingPeriod" JSONB NOT NULL,
    "validationPeriod" JSONB NOT NULL,
    "testPeriod" JSONB NOT NULL,
    "hyperparameters" JSONB NOT NULL,
    "metrics" JSONB NOT NULL,
    "backtestMetrics" JSONB NOT NULL,
    "calibrationVersion" TEXT,
    "artifactPath" TEXT NOT NULL,
    "gates" JSONB NOT NULL,
    "accuracyGate" TEXT NOT NULL,
    "history" JSONB NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL,
    "syncedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "ModelVersion_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "FeatureVersion" (
    "version" TEXT NOT NULL,
    "features" JSONB NOT NULL,
    "count" INTEGER NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "FeatureVersion_pkey" PRIMARY KEY ("version")
);

-- CreateTable
CREATE TABLE "Experiment" (
    "id" TEXT NOT NULL,
    "phase" INTEGER NOT NULL,
    "kind" TEXT NOT NULL,
    "label" TEXT,
    "model" TEXT,
    "summary" JSONB NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Experiment_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Prediction" (
    "id" TEXT NOT NULL,
    "symbol" TEXT NOT NULL,
    "predictionTimestamp" TIMESTAMP(3) NOT NULL,
    "marketDataTimestamp" TIMESTAMP(3) NOT NULL,
    "targetTimestamp" TIMESTAMP(3) NOT NULL,
    "latencyMs" DOUBLE PRECISION NOT NULL,
    "currentPrice" DOUBLE PRECISION,
    "predictedPrice" DOUBLE PRECISION,
    "predictedReturn" DOUBLE PRECISION,
    "direction" "Direction" NOT NULL,
    "modelClass" "Direction" NOT NULL,
    "abstainReason" TEXT,
    "rawProbability" JSONB NOT NULL,
    "calibratedProbability" JSONB NOT NULL,
    "confidence" DOUBLE PRECISION,
    "horizonMinutes" INTEGER NOT NULL,
    "labelThreshold" DOUBLE PRECISION NOT NULL,
    "modelVersionId" TEXT NOT NULL,
    "modelStatus" "ModelStatus" NOT NULL,
    "researchOnly" BOOLEAN NOT NULL,
    "featureVersion" TEXT NOT NULL,
    "dataVersion" TEXT NOT NULL,
    "dataQuality" TEXT NOT NULL,
    "mode" TEXT NOT NULL,
    "requestedById" TEXT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "Prediction_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "PredictionOutcome" (
    "predictionId" TEXT NOT NULL,
    "actualPrice" DOUBLE PRECISION,
    "actualReturn" DOUBLE PRECISION,
    "predictionError" DOUBLE PRECISION,
    "directionCorrect" BOOLEAN,
    "actualClass" "Direction",
    "evaluatedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "PredictionOutcome_pkey" PRIMARY KEY ("predictionId")
);

-- CreateTable
CREATE TABLE "Watchlist" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "Watchlist_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "WatchlistItem" (
    "id" TEXT NOT NULL,
    "watchlistId" TEXT NOT NULL,
    "symbol" TEXT NOT NULL,
    "addedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "WatchlistItem_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Alert" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "symbol" TEXT NOT NULL,
    "condition" "AlertCondition" NOT NULL,
    "threshold" DOUBLE PRECISION,
    "status" "AlertStatus" NOT NULL DEFAULT 'ACTIVE',
    "triggeredAt" TIMESTAMP(3),
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "Alert_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Portfolio" (
    "id" TEXT NOT NULL,
    "userId" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "cash" DOUBLE PRECISION NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "Portfolio_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "PortfolioPosition" (
    "id" TEXT NOT NULL,
    "portfolioId" TEXT NOT NULL,
    "symbol" TEXT NOT NULL,
    "quantity" DOUBLE PRECISION NOT NULL,
    "avgPrice" DOUBLE PRECISION NOT NULL,
    "openedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "PortfolioPosition_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "AuditLog" (
    "id" BIGSERIAL NOT NULL,
    "userId" TEXT,
    "action" TEXT NOT NULL,
    "entity" TEXT,
    "entityId" TEXT,
    "ip" TEXT,
    "detail" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "AuditLog_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "User_email_key" ON "User"("email");

-- CreateIndex
CREATE UNIQUE INDEX "Session_refreshTokenHash_key" ON "Session"("refreshTokenHash");

-- CreateIndex
CREATE INDEX "Session_userId_idx" ON "Session"("userId");

-- CreateIndex
CREATE INDEX "SymbolHistory_symbol_idx" ON "SymbolHistory"("symbol");

-- CreateIndex
CREATE INDEX "MarketData_tradeDate_idx" ON "MarketData"("tradeDate");

-- CreateIndex
CREATE UNIQUE INDEX "ModelVersion_modelId_version_key" ON "ModelVersion"("modelId", "version");

-- CreateIndex
CREATE INDEX "Prediction_symbol_predictionTimestamp_idx" ON "Prediction"("symbol", "predictionTimestamp");

-- CreateIndex
CREATE INDEX "Prediction_modelVersionId_predictionTimestamp_idx" ON "Prediction"("modelVersionId", "predictionTimestamp");

-- CreateIndex
CREATE UNIQUE INDEX "Watchlist_userId_name_key" ON "Watchlist"("userId", "name");

-- CreateIndex
CREATE UNIQUE INDEX "WatchlistItem_watchlistId_symbol_key" ON "WatchlistItem"("watchlistId", "symbol");

-- CreateIndex
CREATE INDEX "Alert_userId_idx" ON "Alert"("userId");

-- CreateIndex
CREATE INDEX "Alert_symbol_status_idx" ON "Alert"("symbol", "status");

-- CreateIndex
CREATE UNIQUE INDEX "Portfolio_userId_name_key" ON "Portfolio"("userId", "name");

-- CreateIndex
CREATE UNIQUE INDEX "PortfolioPosition_portfolioId_symbol_key" ON "PortfolioPosition"("portfolioId", "symbol");

-- CreateIndex
CREATE INDEX "AuditLog_userId_createdAt_idx" ON "AuditLog"("userId", "createdAt");

-- CreateIndex
CREATE INDEX "AuditLog_action_createdAt_idx" ON "AuditLog"("action", "createdAt");

-- AddForeignKey
ALTER TABLE "Session" ADD CONSTRAINT "Session_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "SymbolHistory" ADD CONSTRAINT "SymbolHistory_symbol_fkey" FOREIGN KEY ("symbol") REFERENCES "Stock"("symbol") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "MarketData" ADD CONSTRAINT "MarketData_symbol_fkey" FOREIGN KEY ("symbol") REFERENCES "Stock"("symbol") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Prediction" ADD CONSTRAINT "Prediction_symbol_fkey" FOREIGN KEY ("symbol") REFERENCES "Stock"("symbol") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Prediction" ADD CONSTRAINT "Prediction_modelVersionId_fkey" FOREIGN KEY ("modelVersionId") REFERENCES "ModelVersion"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PredictionOutcome" ADD CONSTRAINT "PredictionOutcome_predictionId_fkey" FOREIGN KEY ("predictionId") REFERENCES "Prediction"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Watchlist" ADD CONSTRAINT "Watchlist_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "WatchlistItem" ADD CONSTRAINT "WatchlistItem_watchlistId_fkey" FOREIGN KEY ("watchlistId") REFERENCES "Watchlist"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "WatchlistItem" ADD CONSTRAINT "WatchlistItem_symbol_fkey" FOREIGN KEY ("symbol") REFERENCES "Stock"("symbol") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Alert" ADD CONSTRAINT "Alert_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Alert" ADD CONSTRAINT "Alert_symbol_fkey" FOREIGN KEY ("symbol") REFERENCES "Stock"("symbol") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Portfolio" ADD CONSTRAINT "Portfolio_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PortfolioPosition" ADD CONSTRAINT "PortfolioPosition_portfolioId_fkey" FOREIGN KEY ("portfolioId") REFERENCES "Portfolio"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "PortfolioPosition" ADD CONSTRAINT "PortfolioPosition_symbol_fkey" FOREIGN KEY ("symbol") REFERENCES "Stock"("symbol") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AuditLog" ADD CONSTRAINT "AuditLog_userId_fkey" FOREIGN KEY ("userId") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;
