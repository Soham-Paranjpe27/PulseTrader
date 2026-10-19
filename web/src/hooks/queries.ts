'use client';

import { useQuery } from '@tanstack/react-query';
import { get, qs } from '@/lib/api';
import type {
  Accuracy,
  DailyBar,
  Indicators,
  LiveStatus,
  MinuteBar,
  ModelVersion,
  Page,
  Prediction,
  Ready,
  Stock,
  StockDetail,
} from '@/lib/types';

export const useFeedStatus = () =>
  useQuery({
    queryKey: ['feed'],
    queryFn: () => get<LiveStatus>('/market-data/status'),
    refetchInterval: 30_000,
  });

export const useReady = () =>
  useQuery({ queryKey: ['ready'], queryFn: () => get<Ready>('/health/ready'), refetchInterval: 30_000 });

export const useModels = () =>
  useQuery({ queryKey: ['models'], queryFn: () => get<ModelVersion[]>('/models') });

export function useStocks(p: {
  q?: string;
  type?: string;
  universe?: string;
  page: number;
  pageSize?: number;
}) {
  return useQuery({
    queryKey: ['stocks', p],
    queryFn: () => get<Page<Stock>>(`/stocks${qs({ ...p, pageSize: p.pageSize ?? 25 })}`),
    placeholderData: (prev) => prev,
  });
}

export const useStock = (symbol: string) =>
  useQuery({
    queryKey: ['stock', symbol],
    queryFn: () => get<StockDetail>(`/stocks/${encodeURIComponent(symbol)}`),
  });

export const useDaily = (symbol: string, from: string | null) =>
  useQuery({
    queryKey: ['daily', symbol, from],
    queryFn: () =>
      get<{ count: number; bars: DailyBar[] }>(
        `/market-data/${encodeURIComponent(symbol)}/daily${qs({ from: from ?? undefined })}`,
      ),
    enabled: from !== null,
  });

export const useIntraday = (symbol: string, date: string | null, enabled = true) =>
  useQuery({
    queryKey: ['intraday', symbol, date],
    queryFn: () =>
      get<{ date: string; count: number; bars: MinuteBar[]; source: string }>(
        `/market-data/${encodeURIComponent(symbol)}/intraday${qs({ date })}`,
      ),
    enabled,
    staleTime: 10 * 60_000,
  });

export const useIndicators = (symbol: string, date: string | null) =>
  useQuery({
    queryKey: ['indicators', symbol, date],
    queryFn: () => get<Indicators>(`/market-data/${encodeURIComponent(symbol)}/indicators${qs({ date })}`),
    staleTime: 10 * 60_000,
  });

export function usePredictions(p: { symbol?: string; direction?: string; model?: string; page: number }) {
  return useQuery({
    queryKey: ['predictions', p],
    queryFn: () => get<Page<Prediction>>(`/predictions${qs({ ...p, pageSize: 25 })}`),
    placeholderData: (prev) => prev,
  });
}

export const useAccuracy = (symbol?: string) =>
  useQuery({
    queryKey: ['accuracy', symbol ?? null],
    queryFn: () => get<Accuracy>(`/predictions/accuracy${qs({ symbol })}`),
  });
