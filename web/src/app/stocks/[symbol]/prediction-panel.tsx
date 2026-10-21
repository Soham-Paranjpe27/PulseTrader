'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import Link from 'next/link';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo } from 'react';
import { useForm } from 'react-hook-form';
import { DirectionBadge, ErrorView, ResearchOnly } from '@/components/status';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input, Select } from '@/components/ui/input';
import { FieldError, Label } from '@/components/ui/label';
import { useMe } from '@/hooks/auth';
import { useModels } from '@/hooks/queries';
import { post } from '@/lib/api';
import { istTime, pct } from '@/lib/format';
import { istTimestamp, type PredictionInput, predictionSchema } from '@/lib/schemas';
import { usePrefs } from '@/lib/store';
import type { Prediction } from '@/lib/types';

function Probabilities({ p, label }: { p: Prediction['rawProbability']; label: string }) {
  const rows: [string, number, string][] = [
    ['Up', p.up, 'bg-up'],
    ['Neutral', p.neutral, 'bg-muted-foreground'],
    ['Down', p.down, 'bg-down'],
  ];
  return (
    <div>
      <p className="text-muted-foreground mb-1 text-xs">{label}</p>
      {rows.map(([k, v, c]) => (
        <div key={k} className="flex items-center gap-2 text-xs">
          <span className="text-muted-foreground w-14">{k}</span>
          <div className="bg-muted h-2 flex-1 rounded">
            <div className={`h-2 rounded ${c}`} style={{ width: `${Math.max(0, Math.min(1, v)) * 100}%` }} />
          </div>
          <span className="w-12 text-right">{pct(v)}</span>
        </div>
      ))}
    </div>
  );
}

export function PredictionDetails({ p }: { p: Prediction }) {
  const item = (k: string, v: React.ReactNode) => (
    <div className="border-border/50 flex justify-between gap-3 border-b py-1 text-sm">
      <span className="text-muted-foreground text-xs">{k}</span>
      <span className="text-right">{v}</span>
    </div>
  );
  return (
    <div className="grid gap-4 md:grid-cols-2" data-testid="prediction">
      <div>
        <div className="mb-2 flex items-center gap-2">
          <DirectionBadge d={p.direction} />
          <ResearchOnly on={p.researchOnly} />
          {p.abstainReason ? (
            <span className="text-muted-foreground font-mono text-xs">{p.abstainReason}</span>
          ) : null}
        </div>
        {item('Market data (bar start)', istTime(p.marketDataTimestamp))}
        {item('Prediction time (bar close)', istTime(p.predictionTimestamp))}
        {item('Prediction horizon', `${p.horizonMinutes} min (target ${istTime(p.targetTimestamp)})`)}
        {item('Label threshold', pct(p.labelThreshold, 2))}
        {item('Model class (argmax)', p.modelClass)}
        {item('Confidence', pct(p.confidence))}
        {item('Model version', `${p.modelVersionId} (${p.modelStatus})`)}
        {item('Feature version', p.featureVersion)}
        {item('Data quality', p.dataQuality)}
        {item(
          'Predicted price',
          p.predictedPrice === null ? 'not produced (no regression model)' : p.predictedPrice,
        )}
      </div>
      <div className="flex flex-col gap-3">
        <Probabilities p={p.rawProbability} label="Raw probability (decides the direction)" />
        <Probabilities p={p.calibratedProbability} label="Calibrated probability (validation-fit isotonic)" />
      </div>
    </div>
  );
}

export function PredictionPanel({
  symbol,
  latest,
  inUniverse,
}: {
  symbol: string;
  latest: Prediction | null;
  inUniverse: boolean;
}) {
  const me = useMe();
  const models = useModels();
  const qc = useQueryClient();
  const prefModel = usePrefs((s) => s.modelId);
  const setPrefModel = usePrefs((s) => s.setModelId);
  const choices = useMemo(
    () => (models.data ?? []).filter((m) => !['RETIRED', 'REJECTED'].includes(m.status)),
    [models.data],
  );
  const form = useForm<PredictionInput>({
    resolver: zodResolver(predictionSchema),
    defaultValues: { modelId: '', date: '', time: '10:30' },
  });
  const chosen = choices.find((m) => m.id === form.watch('modelId'));
  useEffect(() => {
    if (!choices.length || form.getValues('modelId')) return;
    const m = choices.find((c) => c.id === prefModel) ?? choices[0]!;
    form.setValue('modelId', m.id);
    // default to the last validation day: the test period is locked until development is finished
    form.setValue('date', m.validationPeriod.end);
  }, [choices, prefModel, form]);
  const run = useMutation({
    mutationFn: (v: PredictionInput) => {
      const m = choices.find((c) => c.id === v.modelId)!;
      return post<Prediction>('/predictions', {
        symbol,
        timestamp: istTimestamp(v.date, v.time),
        modelId: m.modelId,
        modelVersion: m.version,
      });
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['stock', symbol] });
      void qc.invalidateQueries({ queryKey: ['predictions'] });
      void qc.invalidateQueries({ queryKey: ['accuracy'] });
    },
  });
  const e = form.formState.errors;
  const shown = run.data ?? latest;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Prediction</CardTitle>
        <CardDescription>
          {shown
            ? run.data
              ? 'Just generated.'
              : 'Latest stored prediction.'
            : 'No stored prediction for this symbol yet.'}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {shown ? <PredictionDetails p={shown} /> : null}
        <div className="border-border rounded-md border p-3">
          <p className="mb-2 text-sm font-medium">Run a historical prediction</p>
          <p className="text-muted-foreground mb-3 text-xs">
            The ML service reads the feature row the models were trained on. Rows exist for research-universe
            stocks at 5-minute bar starts in the train and validation periods
            {chosen ? ` (validation ${chosen.validationPeriod.start} to ${chosen.validationPeriod.end})` : ''}
            . The test period answers TEST_PERIOD_LOCKED.
            {!inUniverse
              ? ' This instrument is outside the research universe, so expect DATA_UNAVAILABLE.'
              : ''}
          </p>
          {me.data ? (
            <form
              noValidate
              className="flex flex-wrap items-end gap-3"
              onSubmit={form.handleSubmit((v) => {
                setPrefModel(v.modelId);
                run.mutate(v);
              })}
            >
              <div className="flex min-w-56 flex-col gap-1">
                <Label htmlFor="modelId">Model</Label>
                <Select id="modelId" {...form.register('modelId')}>
                  {choices.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.id} ({m.status})
                    </option>
                  ))}
                </Select>
                <FieldError message={e.modelId?.message} />
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="pred-date">Session (IST)</Label>
                <Input id="pred-date" type="date" className="w-40" {...form.register('date')} />
                <FieldError message={e.date?.message} />
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="pred-time">Bar start</Label>
                <Input id="pred-time" type="time" step={300} className="w-28" {...form.register('time')} />
                <FieldError message={e.time?.message} />
              </div>
              <Button type="submit" disabled={run.isPending || !choices.length}>
                {run.isPending ? 'Running…' : 'Run prediction'}
              </Button>
            </form>
          ) : (
            <p className="text-sm">
              <Link
                className="text-primary hover:underline"
                href={`/login?next=/stocks/${encodeURIComponent(symbol)}`}
              >
                Log in
              </Link>{' '}
              to run predictions.
            </p>
          )}
          {run.error ? (
            <div className="mt-3">
              <ErrorView error={run.error} title="No prediction" />
            </div>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}
