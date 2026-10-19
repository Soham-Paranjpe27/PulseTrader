'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import type { z } from 'zod';
import { ErrorView, PageHeader, RequireAuth } from '@/components/status';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/callout';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input, Select } from '@/components/ui/input';
import { FieldError, Label } from '@/components/ui/label';
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/table';
import { del, get, patch, post } from '@/lib/api';
import { inr, istTime } from '@/lib/format';
import { alertSchema } from '@/lib/schemas';
import type { AlertCondition, PriceAlert } from '@/lib/types';

const KEY = ['alerts'];
const LABEL: Record<AlertCondition, string> = {
  PRICE_ABOVE: 'Close above',
  PRICE_BELOW: 'Close below',
  PREDICTION_UP: 'Latest prediction is UP',
  PREDICTION_DOWN: 'Latest prediction is DOWN',
};

type FormIn = z.input<typeof alertSchema>;
type FormOut = z.output<typeof alertSchema>;

function CreateAlert({ symbol }: { symbol: string }) {
  const qc = useQueryClient();
  const form = useForm<FormIn, unknown, FormOut>({
    resolver: zodResolver(alertSchema),
    defaultValues: { symbol, condition: 'PRICE_ABOVE', threshold: undefined },
  });
  const cond = form.watch('condition');
  const create = useMutation({
    mutationFn: (v: FormOut) =>
      post('/alerts', {
        symbol: v.symbol.toUpperCase(),
        condition: v.condition,
        ...(v.condition.startsWith('PRICE') ? { threshold: v.threshold } : {}),
      }),
    onSuccess: () => {
      form.reset({ symbol: '', condition: 'PRICE_ABOVE', threshold: undefined });
      return qc.invalidateQueries({ queryKey: KEY });
    },
  });
  const e = form.formState.errors;
  return (
    <form
      noValidate
      className="flex flex-wrap items-start gap-3"
      onSubmit={form.handleSubmit((v) => create.mutate(v))}
    >
      <div className="flex flex-col gap-1">
        <Label htmlFor="alert-symbol">Symbol</Label>
        <Input id="alert-symbol" className="w-40" {...form.register('symbol')} />
        <FieldError message={e.symbol?.message} />
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor="alert-condition">Condition</Label>
        <Select id="alert-condition" className="w-56" {...form.register('condition')}>
          {(Object.keys(LABEL) as AlertCondition[]).map((c) => (
            <option key={c} value={c}>
              {LABEL[c]}
            </option>
          ))}
        </Select>
      </div>
      {cond.startsWith('PRICE') ? (
        <div className="flex flex-col gap-1">
          <Label htmlFor="alert-threshold">Price (₹)</Label>
          <Input
            id="alert-threshold"
            type="number"
            step="0.05"
            className="w-32"
            {...form.register('threshold', { setValueAs: (v: string) => (v === '' ? undefined : v) })}
          />
          <FieldError message={e.threshold?.message} />
        </div>
      ) : null}
      <Button type="submit" className="mt-5" disabled={create.isPending}>
        Create alert
      </Button>
      {create.error ? <ErrorView error={create.error} /> : null}
    </form>
  );
}

function AlertsList() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: KEY, queryFn: () => get<PriceAlert[]>('/alerts') });
  const toggle = useMutation({
    mutationFn: (a: PriceAlert) =>
      patch(`/alerts/${a.id}`, { status: a.status === 'DISABLED' ? 'ACTIVE' : 'DISABLED' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
  const remove = useMutation({
    mutationFn: (id: string) => del(`/alerts/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
  if (q.isLoading) return <Skeleton className="h-24 w-full" />;
  if (q.isError) return <ErrorView error={q.error} />;
  if (!q.data?.length) return <p className="text-muted-foreground text-sm">No alerts yet.</p>;
  return (
    <Table data-testid="alerts-table">
      <THead>
        <TR>
          <TH>Symbol</TH>
          <TH>Condition</TH>
          <TH>Status</TH>
          <TH>Triggered</TH>
          <TH>Created</TH>
          <TH />
        </TR>
      </THead>
      <TBody>
        {q.data.map((a) => (
          <TR key={a.id}>
            <TD>
              <Link
                className="text-primary font-medium hover:underline"
                href={`/stocks/${encodeURIComponent(a.symbol)}`}
              >
                {a.symbol}
              </Link>
            </TD>
            <TD>
              {LABEL[a.condition]} {a.threshold !== null ? inr(a.threshold) : ''}
            </TD>
            <TD>
              <Badge tone={a.status === 'ACTIVE' ? 'info' : a.status === 'TRIGGERED' ? 'warn' : 'neutral'}>
                {a.status}
              </Badge>
            </TD>
            <TD className="text-xs">{a.triggeredAt ? istTime(a.triggeredAt) : '–'}</TD>
            <TD className="text-xs">{istTime(a.createdAt)}</TD>
            <TD className="flex justify-end gap-1">
              {a.status !== 'TRIGGERED' ? (
                <Button variant="outline" size="sm" onClick={() => toggle.mutate(a)}>
                  {a.status === 'DISABLED' ? 'Enable' : 'Disable'}
                </Button>
              ) : null}
              <Button variant="ghost" size="sm" onClick={() => remove.mutate(a.id)}>
                Delete
              </Button>
            </TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

export function AlertsView() {
  const params = useSearchParams();
  return (
    <RequireAuth>
      <PageHeader
        title="Alerts"
        description="Checked against the latest stored daily close and the latest stored prediction when the alert evaluator runs (no live prices yet)."
      />
      <div className="flex flex-col gap-4">
        <Card>
          <CardHeader>
            <CardTitle>New alert</CardTitle>
            <CardDescription>
              Price alerts need a price; prediction alerts fire when the latest stored prediction for the
              symbol matches.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <CreateAlert symbol={(params.get('symbol') ?? '').toUpperCase()} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Your alerts</CardTitle>
          </CardHeader>
          <CardContent>
            <AlertsList />
          </CardContent>
        </Card>
      </div>
    </RequireAuth>
  );
}
