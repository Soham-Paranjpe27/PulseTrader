'use client';

import { create } from 'zustand';
import { createJSONStorage, persist } from 'zustand/middleware';

export type Theme = 'dark' | 'light' | 'system';
export type ChartMode = 'daily' | 'intraday';

interface Prefs {
  theme: Theme;
  chartMode: ChartMode;
  /** model used for "Run prediction"; null = first loaded model */
  modelId: string | null;
  setTheme: (t: Theme) => void;
  setChartMode: (m: ChartMode) => void;
  setModelId: (id: string | null) => void;
}

/** Per-browser UI preferences (never anything sensitive). */
export const usePrefs = create<Prefs>()(
  persist(
    (set) => ({
      theme: 'dark',
      chartMode: 'daily',
      modelId: null,
      setTheme: (theme) => set({ theme }),
      setChartMode: (chartMode) => set({ chartMode }),
      setModelId: (modelId) => set({ modelId }),
    }),
    { name: 'pulsetrader-prefs', storage: createJSONStorage(() => localStorage) },
  ),
);
