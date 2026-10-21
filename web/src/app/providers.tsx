'use client';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { ApiError } from '@/lib/api';
import { usePrefs } from '@/lib/store';

function ThemeSync() {
  const theme = usePrefs((s) => s.theme);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  return null;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            refetchOnWindowFocus: false,
            // never retry client errors (401/403/404/409 are answers, e.g. TEST_PERIOD_LOCKED)
            retry: (n, e) => !(e instanceof ApiError && e.status < 500) && n < 2,
          },
        },
      }),
  );
  return (
    <QueryClientProvider client={client}>
      <ThemeSync />
      {children}
    </QueryClientProvider>
  );
}
