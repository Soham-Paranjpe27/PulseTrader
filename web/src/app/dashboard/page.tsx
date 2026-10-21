'use client';

import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { ModelsTable } from '@/components/models-table';
import { AccuracyGrid, PredictionsTable } from '@/components/predictions-table';
import { ErrorView, PageHeader, RequireAuth } from '@/components/status';
import { Badge } from '@/components/ui/badge';
import { Callout, Skeleton } from '@/components/ui/callout';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useAccuracy, useModels, usePredictions, useReady } from '@/hooks/queries';
import { get } from '@/lib/api';
import { pct } from '@/lib/format';
import type { Watchlist } from '@/lib/types';

function Health() {
  const q = useReady();
  if (q.isLoading) return <Skeleton className="h-20 w-full" />;
  if (q.isError) return <ErrorView error={q.error} />;
  const r = q.data!;
  const item = (name: string, ok: boolean, detail?: string | null) => (
    <div className="border-border flex items-center justify-between rounded-md border px-3 py-2">
      <span className="text-sm">{name}</span>
      <span className="text-muted-foreground flex items-center gap-2 text-xs">
        {detail}
        <Badge tone={ok ? 'up' : 'down'}>{ok ? 'OK' : 'DOWN'}</Badge>
      </span>
    </div>
  );
  return (
    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4" data-testid="health">
      {item('Database', r.database)}
      {item('Redis', r.redis)}
      {item('ML service', r.mlService.reachable && r.mlService.ready !== false, r.mlService.reason ?? null)}
      <div className="border-border flex items-center justify-between rounded-md border px-3 py-2">
        <span className="text-sm">Market data feed</span>
        <Badge title={r.marketData.reason}>{r.marketData.state}</Badge>
      </div>
    </div>
  );
}

function Watchlists() {
  const q = useQuery({ queryKey: ['watchlists'], queryFn: () => get<Watchlist[]>('/watchlists') });
  if (q.isLoading) return <Skeleton className="h-16 w-full" />;
  if (q.isError) return <ErrorView error={q.error} />;
  if (!q.data?.length)
    return (
      <p className="text-muted-foreground text-sm">
        No watchlists yet.{' '}
        <Link className="text-primary hover:underline" href="/watchlist">
          Create one
        </Link>
        .
      </p>
    );
  return (
    <ul className="flex flex-col gap-2">
      {q.data.map((w) => (
        <li key={w.id} className="flex flex-wrap items-center gap-1.5 text-sm">
          <span className="mr-1 font-medium">{w.name}</span>
          {w.items.map((i) => (
            <Link key={i.id} href={`/stocks/${encodeURIComponent(i.symbol)}`}>
              <Badge tone="info">{i.symbol}</Badge>
            </Link>
          ))}
          {!w.items.length ? <span className="text-muted-foreground text-xs">empty</span> : null}
        </li>
      ))}
    </ul>
  );
}

function ProductionNotice() {
  const models = useModels();
  if (!models.data || models.data.some((m) => m.status === 'PRODUCTION')) return null;
  const failed = [
    ...new Set(
      models.data.flatMap((m) =>
        Object.entries(m.gates)
          .filter(([, v]) => v === 'FAILED')
          .map(([k]) => k),
      ),
    ),
  ];
  return (
    <Callout tone="warn" title="No production model">
      No registered model has passed every promotion gate
      {failed.length ? ` (failed: ${failed.join(', ')})` : ''}. Predictions run only when you pick a model and
      are stored as research only. Prices are historical; no live feed is connected.
    </Callout>
  );
}

export default function Dashboard() {
  const preds = usePredictions({ page: 1 });
  const acc = useAccuracy();
  return (
    <RequireAuth>
      <PageHeader title="Dashboard" description="System state, models and your latest activity." />
      <div className="flex flex-col gap-4">
        <Health />
        <ProductionNotice />
        <Card>
          <CardHeader>
            <CardTitle>Models</CardTitle>
            <CardDescription>Validation metrics and promotion gates from the registry.</CardDescription>
          </CardHeader>
          <CardContent>
            <ModelsTable showGates />
          </CardContent>
        </Card>
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle>Prediction accuracy (stored predictions)</CardTitle>
              <CardDescription>
                {acc.data
                  ? `${acc.data.predictions} stored, ${acc.data.directional} directional, coverage ${pct(acc.data.coverage)}, ${acc.data.evaluated} evaluated.`
                  : ' '}
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              <AccuracyGrid rolling={acc.data?.rolling} />
              {acc.data?.note ? <p className="text-muted-foreground text-xs">{acc.data.note}</p> : null}
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Watchlists</CardTitle>
            </CardHeader>
            <CardContent>
              <Watchlists />
            </CardContent>
          </Card>
        </div>
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <CardTitle>Latest predictions</CardTitle>
            <Link className="text-primary text-xs hover:underline" href="/predictions">
              All predictions
            </Link>
          </CardHeader>
          <CardContent>
            {preds.isError ? (
              <ErrorView error={preds.error} />
            ) : (
              <PredictionsTable rows={(preds.data?.items ?? []).slice(0, 8)} />
            )}
          </CardContent>
        </Card>
      </div>
    </RequireAuth>
  );
}
