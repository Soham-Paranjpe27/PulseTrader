'use client';

import { useEffect, useState } from 'react';
import type { Prediction } from '@/lib/types';

export type StreamState = 'connecting' | 'open' | 'closed';

/**
 * Server-sent prediction events (GET /api/predictions/stream, login required). This is the app's own
 * event stream; it says nothing about the market-data feed, which has its own state.
 */
export function usePredictionStream(enabled: boolean, max = 50) {
  const [events, setEvents] = useState<Prediction[]>([]);
  const [state, setState] = useState<StreamState>('closed');
  useEffect(() => {
    if (!enabled) return;
    setState('connecting');
    const es = new EventSource('/api/predictions/stream', { withCredentials: true });
    es.onopen = () => setState('open');
    es.onerror = () => setState(es.readyState === EventSource.CLOSED ? 'closed' : 'connecting');
    es.onmessage = (m: MessageEvent<string>) => {
      try {
        const p = JSON.parse(m.data) as Prediction;
        setEvents((prev) => [p, ...prev].slice(0, max));
      } catch (e) {
        console.error('prediction stream: bad event', e);
      }
    };
    return () => {
      es.close();
      setState('closed');
    };
  }, [enabled, max]);
  return { events, state };
}
