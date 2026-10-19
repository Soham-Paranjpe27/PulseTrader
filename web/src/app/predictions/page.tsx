'use client';

import { useState } from 'react';
import { AccuracyGrid, PredictionsTable } from '@/components/predictions-table';
import { ErrorView, PageHeader } from '@/components/status';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/callout';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input, Select } from '@/components/ui/input';
import { useMe } from '@/hooks/auth';
import { useAccuracy, useModels, usePredictions } from '@/hooks/queries';
import { useDebounced } from '@/hooks/use-debounced';
import { usePredictionStream } from '@/hooks/use-prediction-stream';
import { pct } from '@/lib/format';

export default function PredictionsPage() {
  const me = useMe();
  const models = useModels();
  const [symbol, setSymbol] = useState('');
  const [direction, setDirection] = useState('');
  const [model, setModel] = useState('');
  const [page, setPage] = useState(1);
  const sym = useDebounced(symbol.trim().toUpperCase());
  const res = usePredictions({
    symbol: sym || undefined,
    direction: direction || undefined,
    model: model || undefined,
    page,
  });
  const acc = useAccuracy(sym || undefined);
  const stream = usePredictionStream(!!me.data);
  const pages = Math.max(1, Math.ceil((res.data?.total ?? 0) / 25));
  return (
    <>
      <PageHeader
        title="Predictions"
        description="Every stored prediction, including abstentions (NO_PREDICTION with its reason)."
      />
      <div className="flex flex-col gap-4">
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader>
              <CardTitle>Accuracy {sym ? `for ${sym}` : ''}</CardTitle>
              <CardDescription>
                {acc.data
                  ? `${acc.data.predictions} predictions, ${acc.data.directional} directional (coverage ${pct(acc.data.coverage)}), ${acc.data.evaluated} with evaluated outcomes.`
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
              <CardTitle className="flex items-center gap-2">
                Prediction stream
                <Badge tone={stream.state === 'open' ? 'up' : 'neutral'} data-testid="stream-state">
                  {me.data ? stream.state.toUpperCase() : 'LOG IN TO CONNECT'}
                </Badge>
              </CardTitle>
              <CardDescription>New predictions from any user appear here as they are stored.</CardDescription>
            </CardHeader>
            <CardContent>
              {stream.events.length ? (
                <ul
                  className="flex max-h-48 flex-col gap-1 overflow-y-auto text-xs"
                  data-testid="stream-events"
                >
                  {stream.events.map((p) => (
                    <li key={p.id} className="flex justify-between gap-2">
                      <span className="font-medium">{p.symbol}</span>
                      <span>{p.direction}</span>
                      <span className="text-muted-foreground">{p.modelVersionId}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-muted-foreground text-xs">No new predictions since this page opened.</p>
              )}
            </CardContent>
          </Card>
        </div>
        <Card>
          <CardContent className="flex flex-col gap-3 pt-4">
            <div className="flex flex-wrap gap-2">
              <Input
                aria-label="Filter by symbol"
                placeholder="Symbol"
                className="w-40"
                value={symbol}
                onChange={(e) => {
                  setSymbol(e.target.value);
                  setPage(1);
                }}
              />
              <Select
                aria-label="Direction"
                className="w-44"
                value={direction}
                onChange={(e) => (setDirection(e.target.value), setPage(1))}
              >
                <option value="">Any direction</option>
                <option value="UP">UP</option>
                <option value="DOWN">DOWN</option>
                <option value="NO_PREDICTION">NO_PREDICTION</option>
              </Select>
              <Select
                aria-label="Model"
                className="w-72"
                value={model}
                onChange={(e) => (setModel(e.target.value), setPage(1))}
              >
                <option value="">Any model</option>
                {(models.data ?? []).map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.id}
                  </option>
                ))}
              </Select>
              <span className="text-muted-foreground ml-auto self-center text-xs">
                {res.data?.total ?? 0} predictions
              </span>
            </div>
            {res.isError ? <ErrorView error={res.error} /> : null}
            {res.isLoading ? (
              <Skeleton className="h-40 w-full" />
            ) : (
              <PredictionsTable rows={res.data?.items ?? []} />
            )}
            <div className="flex items-center justify-end gap-2 text-xs">
              <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                Previous
              </Button>
              <span>
                Page {page} of {pages}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= pages}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
