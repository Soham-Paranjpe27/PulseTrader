import type { DailyBar, MinuteBar } from './types';

/** lightweight-charts plots UTC; shift minute bars by +5:30 so the time axis reads IST. */
export const IST_OFFSET_SECONDS = 19_800;

export interface Candle {
  time: number | string;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface VolumeBar {
  time: number | string;
  value: number;
  up: boolean;
}

export function dailyCandles(bars: DailyBar[]): { candles: Candle[]; volume: VolumeBar[] } {
  const sorted = [...bars].sort((a, b) => a.tradeDate.localeCompare(b.tradeDate));
  const candles: Candle[] = [];
  const volume: VolumeBar[] = [];
  let last = '';
  for (const b of sorted) {
    const time = b.tradeDate.slice(0, 10);
    if (time === last) continue; // the chart needs strictly increasing times
    last = time;
    candles.push({ time, open: b.open, high: b.high, low: b.low, close: b.close });
    volume.push({ time, value: b.volume, up: b.close >= b.open });
  }
  return { candles, volume };
}

export function minuteCandles(bars: MinuteBar[]): { candles: Candle[]; volume: VolumeBar[] } {
  const rows = bars
    .map((b) => ({ ...b, t: Math.floor(new Date(b.ts).getTime() / 1000) + IST_OFFSET_SECONDS }))
    .filter((b) => Number.isFinite(b.t))
    .sort((a, b) => a.t - b.t);
  const candles: Candle[] = [];
  const volume: VolumeBar[] = [];
  let last = -1;
  for (const b of rows) {
    if (b.t === last) continue;
    last = b.t;
    candles.push({ time: b.t, open: b.open, high: b.high, low: b.low, close: b.close });
    volume.push({ time: b.t, value: b.volume, up: b.close >= b.open });
  }
  return { candles, volume };
}

/** Start date for a daily-chart lookback of `days` calendar days before `end` (YYYY-MM-DD). */
export function lookbackStart(end: string, days: number): string {
  const d = new Date(`${end}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}
