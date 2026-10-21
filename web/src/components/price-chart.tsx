'use client';

import { useEffect, useRef } from 'react';
import type { Candle, VolumeBar } from '@/lib/chart';

function cssVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback;
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

/** Candlestick + volume chart (lightweight-charts v5). Intraday times are pre-shifted to IST. */
export function PriceChart({
  candles,
  volume,
  intraday,
  height = 380,
}: {
  candles: Candle[];
  volume: VolumeBar[];
  intraday: boolean;
  height?: number;
}) {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = el.current;
    if (!node) return;
    let disposed = false;
    let cleanup = () => {};
    void import('lightweight-charts').then(
      ({ createChart, CandlestickSeries, HistogramSeries, ColorType }) => {
        if (disposed) return;
        const up = cssVar('--up', '#22c48a');
        const down = cssVar('--down', '#ef4b5f');
        const text = cssVar('--muted-foreground', '#8a94a8');
        const grid = cssVar('--border', '#232c3f');
        const chart = createChart(node, {
          height,
          autoSize: true,
          layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: text },
          grid: { vertLines: { color: grid }, horzLines: { color: grid } },
          rightPriceScale: { borderColor: grid },
          timeScale: { borderColor: grid, timeVisible: intraday, secondsVisible: false },
          crosshair: { mode: 0 },
        });
        const series = chart.addSeries(CandlestickSeries, {
          upColor: up,
          downColor: down,
          borderVisible: false,
          wickUpColor: up,
          wickDownColor: down,
        });
        // lightweight-charts types its Time union strictly; our times are already valid (date string or seconds)
        series.setData(candles as never);
        const vol = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, priceScaleId: '' });
        vol.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
        vol.setData(
          volume.map((v) => ({
            time: v.time,
            value: v.value,
            color: v.up ? `${up}66` : `${down}66`,
          })) as never,
        );
        chart.timeScale().fitContent();
        cleanup = () => chart.remove();
      },
    );
    return () => {
      disposed = true;
      cleanup();
    };
  }, [candles, volume, intraday, height]);
  return <div ref={el} style={{ height }} className="w-full" data-testid="price-chart" />;
}

/** Small line chart for one indicator series (e.g. RSI 14 through the session). */
export function SparkLine({
  points,
  height = 80,
}: {
  points: { time: number; value: number }[];
  height?: number;
}) {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = el.current;
    if (!node || !points.length) return;
    let disposed = false;
    let cleanup = () => {};
    void import('lightweight-charts').then(({ createChart, LineSeries, ColorType }) => {
      if (disposed) return;
      const chart = createChart(node, {
        height,
        autoSize: true,
        // explicit locale: lightweight-charts otherwise uses navigator.language, which can be a tag
        // Intl rejects (e.g. en-US@posix), and the chart then fails to draw
        localization: { locale: 'en-IN' },
        layout: {
          background: { type: ColorType.Solid, color: 'transparent' },
          textColor: cssVar('--muted-foreground', '#8a94a8'),
        },
        grid: { vertLines: { visible: false }, horzLines: { visible: false } },
        rightPriceScale: { visible: true, borderVisible: false },
        timeScale: { visible: false },
        handleScroll: false,
        handleScale: false,
      });
      chart
        .addSeries(LineSeries, {
          color: cssVar('--primary', '#4f8cff'),
          lineWidth: 2,
          priceLineVisible: false,
        })
        .setData(points as never);
      chart.timeScale().fitContent();
      cleanup = () => chart.remove();
    });
    return () => {
      disposed = true;
      cleanup();
    };
  }, [points, height]);
  return <div ref={el} style={{ height }} className="w-full" />;
}
