'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';
import { AccuracyGrid, PredictionsTable } from '@/components/predictions-table';
import { PriceChart, SparkLine } from '@/components/price-chart';
import { ErrorView, Stat } from '@/components/status';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Callout, Skeleton } from '@/components/ui/callout';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { useDaily, useIndicators, useIntraday, usePredictions, useStock } from '@/hooks/queries';
import { dailyCandles, IST_OFFSET_SECONDS, lookbackStart, minuteCandles } from '@/lib/chart';
import { compact, day, inr, istTime, num, pct } from '@/lib/format';
import { usePrefs } from '@/lib/store';
import type { Indicators } from '@/lib/types';
import { AddToWatchlist } from './add-to-watchlist';
import { PredictionPanel } from './prediction-panel';

const PCT = new Set([
  'atr_pct_14',
  'bb_width_20',
  'vwap_dist',
  'sma_20_ratio',
  'sma_50_ratio',
  'ema_20_ratio',
  'realized_vol_30',
  'ret_since_open',
]);

export function indicatorValue(name: string, v: number | null): string {
  if (v === null) return '–';
  if (PCT.has(name)) return pct(v, 2);
  if (name.startsWith('macd')) return num(v * 100, 3) + '%';
  return num(v, 2);
}

function IndicatorsCard({ q }: { q: ReturnType<typeof useIndicators> }) {
  const rsi = useMemo(
    () =>
      (q.data?.series.rsi_14 ?? [])
        .filter((p): p is { ts: string; value: number } => p.value !== null)
        .map((p) => ({
          time: Math.floor(new Date(p.ts).getTime() / 1000) + IST_OFFSET_SECONDS,
          value: p.value,
        })),
    [q.data],
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle>Technical indicators</CardTitle>
        <CardDescription>
          {q.data
            ? `Session ${q.data.date}, last closed bar ${istTime(q.data.bar_ts)}. Computed by the shared feature engine (${q.data.feature_version}) used in training.`
            : 'From the shared feature engine used in training.'}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {q.isLoading ? <Skeleton className="h-40 w-full" /> : null}
        {q.isError ? <ErrorView error={q.error} /> : null}
        {q.data ? (
          <div className="flex flex-col gap-3">
            <dl
              className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm sm:grid-cols-3"
              data-testid="indicators"
            >
              {q.data.latest.map((i) => (
                <div key={i.name} className="border-border/50 flex justify-between gap-2 border-b py-0.5">
                  <dt className="text-muted-foreground truncate text-xs" title={i.name}>
                    {i.label}
                  </dt>
                  <dd className="font-medium">{indicatorValue(i.name, i.value)}</dd>
                </div>
              ))}
            </dl>
            {rsi.length ? (
              <div>
                <p className="text-muted-foreground text-xs">RSI 14 through the session</p>
                <SparkLine points={rsi} />
              </div>
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function RegimeCard({ ind }: { ind: Indicators | undefined }) {
  const r = ind?.regime;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Market regime</CardTitle>
        <CardDescription>NIFTY state known at the session open.</CardDescription>
      </CardHeader>
      <CardContent data-testid="regime">
        {!r ? (
          <Skeleton className="h-12 w-full" />
        ) : r.status === 'OK' ? (
          <div className="flex flex-col gap-2 text-sm">
            <div className="flex gap-2">
              <Badge tone={r.trend === 'up' ? 'up' : 'down'}>TREND {r.trend.toUpperCase()}</Badge>
              <Badge tone="info">VOLATILITY {(r.volatility ?? 'unknown').toUpperCase()}</Badge>
            </div>
            <p className="text-muted-foreground text-xs">{r.definition}</p>
          </div>
        ) : (
          <p className="text-sm">
            <span className="font-mono text-xs">DATA_UNAVAILABLE</span> {r.reason}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export function StockView({ symbol }: { symbol: string }) {
  const detail = useStock(symbol);
  const mode = usePrefs((s) => s.chartMode);
  const setMode = usePrefs((s) => s.setChartMode);
  const [session, setSession] = useState<string | null>(null);
  const quote = detail.data?.quote ?? null;
  const daily = useDaily(symbol, quote ? lookbackStart(quote.tradeDate.slice(0, 10), 365) : null);
  const intraday = useIntraday(symbol, session, mode === 'intraday');
  const shownSession = session ?? intraday.data?.date ?? null;
  const ind = useIndicators(symbol, session);
  const preds = usePredictions({ symbol, page: 1 });

  const chart = useMemo(() => {
    if (mode === 'intraday') return intraday.data ? minuteCandles(intraday.data.bars) : null;
    return daily.data ? dailyCandles(daily.data.bars) : null;
  }, [mode, daily.data, intraday.data]);

  if (detail.isLoading) return <Skeleton className="h-96 w-full" />;
  if (detail.isError) return <ErrorView error={detail.error} />;
  const d = detail.data!;
  const lastMinute = intraday.data?.bars.at(-1)?.ts ?? null;
  // a real-time price replaces the stored close only when the feed is real (LIVE or DELAYED);
  // a replayed session's price is mentioned in the REPLAY notice, never shown as the current price
  const live =
    d.livePrice && (d.livePrice.state === 'LIVE' || d.livePrice.state === 'DELAYED') ? d.livePrice : null;
  const replay = d.livePrice?.state === 'REPLAY' ? d.livePrice : null;
  const chg = live && quote ? live.close - quote.close : (quote?.change ?? null);
  const chgPct = live && quote ? live.close / quote.close - 1 : quote?.changePct;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold tracking-tight" data-testid="symbol">
          {symbol}
        </h1>
        <Badge>{d.stock.instrumentType}</Badge>
        {d.stock.sector ? <Badge tone="neutral">{d.stock.sector}</Badge> : null}
        {d.stock.inResearchUniverse ? <Badge tone="info">RESEARCH UNIVERSE</Badge> : null}
        <Badge
          tone={d.liveStatus.state === 'LIVE' ? 'up' : 'neutral'}
          title={d.liveStatus.reason}
          data-testid="live-status"
        >
          LIVE STATUS: {d.liveStatus.state}
        </Badge>
        <div className="ml-auto flex gap-2">
          <AddToWatchlist symbol={symbol} />
          <Button variant="outline" size="sm" asChild>
            <Link href={`/alerts?symbol=${encodeURIComponent(symbol)}`}>Create alert</Link>
          </Button>
        </div>
      </div>

      <Card>
        <CardContent className="grid grid-cols-2 gap-4 pt-4 md:grid-cols-4">
          {live ? (
            <Stat
              label={live.state === 'LIVE' ? 'Live price' : 'Delayed price'}
              value={inr(live.close)}
              sub={`${live.state.toLowerCase()} 1-min close, bar ${istTime(live.ts)}`}
              testId="price"
            />
          ) : (
            <Stat
              label="Current price"
              value={inr(quote?.close)}
              sub="latest stored daily close (not live)"
              testId="price"
            />
          )}
          <Stat
            label={live ? 'Change' : "Today's change"}
            value={chg === null ? '–' : `${chg > 0 ? '+' : ''}${num(chg)} (${pct(chgPct, 2, true)})`}
            tone={chg === null ? undefined : chg > 0 ? 'up' : chg < 0 ? 'down' : undefined}
            sub={live ? `vs stored close ${day(quote?.tradeDate)}` : 'vs previous stored close'}
          />
          <Stat label="Volume" value={compact(quote?.volume)} sub={`session ${day(quote?.tradeDate)}`} />
          <Stat
            label="Latest market timestamp"
            value={lastMinute ? istTime(lastMinute) : day(quote?.tradeDate)}
            sub={lastMinute ? 'last minute bar loaded' : 'daily bar date'}
            testId="market-ts"
          />
        </CardContent>
      </Card>
      {d.liveStatus.state !== 'LIVE' ? (
        <Callout tone="neutral" title={`Feed ${d.liveStatus.state}`}>
          {d.liveStatus.state === 'REPLAY'
            ? `A recorded session is being replayed through the live pipeline to test it. This is not live data${
                replay ? ` (replay at ${istTime(replay.ts)}: ${inr(replay.close)})` : ''
              }. `
            : `${d.liveStatus.reason}. `}
          Charts show stored historical data ({quote?.source ?? 'no source'}).
        </Callout>
      ) : null}

      <Card>
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle>Price</CardTitle>
            <CardDescription>
              {mode === 'daily'
                ? 'Daily candles, last 12 months of stored bars.'
                : `1-minute candles, session ${shownSession ?? '…'} (IST).`}
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            {mode === 'intraday' ? (
              <Input
                type="date"
                aria-label="Session date"
                className="w-40"
                value={shownSession ?? ''}
                onChange={(e) => setSession(e.target.value || null)}
              />
            ) : null}
            <div className="border-border flex rounded-md border p-0.5" role="tablist">
              {(['daily', 'intraday'] as const).map((m) => (
                <button
                  key={m}
                  role="tab"
                  aria-selected={mode === m}
                  onClick={() => setMode(m)}
                  className={`rounded px-3 py-1 text-xs ${mode === m ? 'bg-accent text-foreground' : 'text-muted-foreground'}`}
                >
                  {m === 'daily' ? 'Daily' : 'Intraday'}
                </button>
              ))}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {(mode === 'daily' ? daily.error : intraday.error) ? (
            <ErrorView error={mode === 'daily' ? daily.error : intraday.error} />
          ) : chart && chart.candles.length ? (
            <PriceChart candles={chart.candles} volume={chart.volume} intraday={mode === 'intraday'} />
          ) : chart ? (
            <p className="text-muted-foreground text-sm">No bars for this range.</p>
          ) : (
            <Skeleton className="h-[380px] w-full" />
          )}
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <IndicatorsCard q={ind} />
        </div>
        <RegimeCard ind={ind.data} />
      </div>

      <PredictionPanel symbol={symbol} latest={d.latestPrediction} inUniverse={d.stock.inResearchUniverse} />

      <Card>
        <CardHeader>
          <CardTitle>Recent prediction accuracy</CardTitle>
          <CardDescription>
            Direction accuracy over evaluated UP/DOWN calls for {symbol} (abstentions excluded).
          </CardDescription>
        </CardHeader>
        <CardContent>
          <AccuracyGrid rolling={d.recentAccuracy} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Predictions for {symbol}</CardTitle>
        </CardHeader>
        <CardContent>
          {preds.isError ? (
            <ErrorView error={preds.error} />
          ) : (
            <PredictionsTable rows={preds.data?.items ?? []} showSymbol={false} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
