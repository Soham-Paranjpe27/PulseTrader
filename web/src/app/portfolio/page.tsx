'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import Link from 'next/link';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import type { z } from 'zod';
import { ErrorView, PageHeader, RequireAuth, Stat } from '@/components/status';
import { Button } from '@/components/ui/button';
import { Callout, Skeleton } from '@/components/ui/callout';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input, Select } from '@/components/ui/input';
import { FieldError, Label } from '@/components/ui/label';
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/table';
import { del, get, post } from '@/lib/api';
import { day, inr, num } from '@/lib/format';
import { portfolioSchema, tradeSchema } from '@/lib/schemas';
import type { Portfolio, PortfolioDetail } from '@/lib/types';

type PIn = z.input<typeof portfolioSchema>;
type POut = z.output<typeof portfolioSchema>;
type TIn = z.input<typeof tradeSchema>;
type TOut = z.output<typeof tradeSchema>;

function CreatePortfolio({ onCreated }: { onCreated: (id: string) => void }) {
  const qc = useQueryClient();
  const form = useForm<PIn, unknown, POut>({
    resolver: zodResolver(portfolioSchema),
    defaultValues: { name: '', cash: 1_000_000 },
  });
  const create = useMutation({
    mutationFn: (v: POut) => post<Portfolio>('/portfolios', v),
    onSuccess: async (p) => {
      form.reset({ name: '', cash: 1_000_000 });
      await qc.invalidateQueries({ queryKey: ['portfolios'] });
      onCreated(p.id);
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
        <Label htmlFor="pf-name">Name</Label>
        <Input id="pf-name" className="w-48" {...form.register('name')} />
        <FieldError message={e.name?.message} />
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor="pf-cash">Starting cash (₹)</Label>
        <Input id="pf-cash" type="number" className="w-40" {...form.register('cash')} />
        <FieldError message={e.cash?.message} />
      </div>
      <Button type="submit" className="mt-5" disabled={create.isPending}>
        Create portfolio
      </Button>
      {create.error ? <ErrorView error={create.error} /> : null}
    </form>
  );
}

function Trade({ id }: { id: string }) {
  const qc = useQueryClient();
  const form = useForm<TIn, unknown, TOut>({
    resolver: zodResolver(tradeSchema),
    defaultValues: { symbol: '', side: 'BUY', quantity: 10 },
  });
  const trade = useMutation({
    mutationFn: (v: TOut) =>
      post<{ price: number; priceDate: string; realizedPnl: number }>(`/portfolios/${id}/trades`, {
        ...v,
        symbol: v.symbol.toUpperCase(),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['portfolio', id] }),
  });
  const e = form.formState.errors;
  return (
    <div className="flex flex-col gap-2">
      <form
        noValidate
        className="flex flex-wrap items-start gap-3"
        onSubmit={form.handleSubmit((v) => trade.mutate(v))}
      >
        <div className="flex flex-col gap-1">
          <Label htmlFor="tr-symbol">Symbol</Label>
          <Input id="tr-symbol" className="w-36" {...form.register('symbol')} />
          <FieldError message={e.symbol?.message} />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="tr-side">Side</Label>
          <Select id="tr-side" className="w-24" {...form.register('side')}>
            <option value="BUY">Buy</option>
            <option value="SELL">Sell</option>
          </Select>
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="tr-qty">Quantity</Label>
          <Input id="tr-qty" type="number" className="w-28" {...form.register('quantity')} />
          <FieldError message={e.quantity?.message} />
        </div>
        <Button type="submit" className="mt-5" disabled={trade.isPending}>
          Place paper trade
        </Button>
      </form>
      {trade.data ? (
        <p className="text-muted-foreground text-xs" data-testid="trade-result">
          Filled at {inr(trade.data.price)} (stored close of {day(trade.data.priceDate)}). Realised P&amp;L{' '}
          {inr(trade.data.realizedPnl)}.
        </p>
      ) : null}
      {trade.error ? <ErrorView error={trade.error} title="Trade rejected" /> : null}
    </div>
  );
}

function PortfolioView({ id, onDeleted }: { id: string; onDeleted: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ['portfolio', id],
    queryFn: () => get<PortfolioDetail>(`/portfolios/${id}`),
  });
  const remove = useMutation({
    mutationFn: () => del(`/portfolios/${id}`),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ['portfolios'] });
      onDeleted();
    },
  });
  if (q.isLoading) return <Skeleton className="h-40 w-full" />;
  if (q.isError) return <ErrorView error={q.error} />;
  const p = q.data!;
  const v = p.valuation;
  return (
    <Card data-testid="portfolio">
      <CardHeader className="flex-row items-start justify-between">
        <div>
          <CardTitle>{p.name}</CardTitle>
          <CardDescription>{p.pricing}</CardDescription>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => confirm(`Delete portfolio "${p.name}"?`) && remove.mutate()}
        >
          Delete
        </Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
          <Stat label="Equity" value={inr(v.equity)} testId="equity" />
          <Stat label="Cash" value={inr(v.cash)} testId="cash" />
          <Stat label="Market value" value={inr(v.marketValue)} />
          <Stat label="Cost basis" value={inr(v.costBasis)} />
          <Stat
            label="Unrealised P&L"
            value={inr(v.unrealizedPnl)}
            tone={v.unrealizedPnl > 0 ? 'up' : v.unrealizedPnl < 0 ? 'down' : undefined}
            sub={v.unpricedPositions ? `${v.unpricedPositions} unpriced` : undefined}
          />
        </div>
        <Trade id={id} />
        {p.positions.length ? (
          <Table data-testid="positions">
            <THead>
              <TR>
                <TH>Symbol</TH>
                <TH className="text-right">Quantity</TH>
                <TH className="text-right">Avg price</TH>
                <TH className="text-right">Last close</TH>
                <TH>Close date</TH>
                <TH className="text-right">Market value</TH>
                <TH className="text-right">Unrealised P&amp;L</TH>
              </TR>
            </THead>
            <TBody>
              {p.positions.map((x) => {
                const pnl = x.price === null ? null : (x.price - x.avgPrice) * x.quantity;
                return (
                  <TR key={x.id}>
                    <TD>
                      <Link
                        className="text-primary font-medium hover:underline"
                        href={`/stocks/${encodeURIComponent(x.symbol)}`}
                      >
                        {x.symbol}
                      </Link>
                    </TD>
                    <TD className="text-right">{num(x.quantity, 0)}</TD>
                    <TD className="text-right">{inr(x.avgPrice)}</TD>
                    <TD className="text-right">{inr(x.price)}</TD>
                    <TD className="text-xs">{day(x.priceDate)}</TD>
                    <TD className="text-right">{x.price === null ? '–' : inr(x.price * x.quantity)}</TD>
                    <TD className={`text-right ${pnl === null ? '' : pnl >= 0 ? 'text-up' : 'text-down'}`}>
                      {inr(pnl)}
                    </TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        ) : (
          <p className="text-muted-foreground text-sm">No positions.</p>
        )}
      </CardContent>
    </Card>
  );
}

function Portfolios() {
  const list = useQuery({ queryKey: ['portfolios'], queryFn: () => get<Portfolio[]>('/portfolios') });
  const [sel, setSel] = useState<string | null>(null);
  const current = sel && list.data?.some((p) => p.id === sel) ? sel : (list.data?.[0]?.id ?? null);
  return (
    <div className="flex flex-col gap-4">
      <Callout tone="neutral" title="Paper trading only">
        Long-only paper portfolios. Trades fill at the latest stored daily close; no broker is connected and
        no costs are charged here (the research backtests do include Indian intraday costs).
      </Callout>
      <Card>
        <CardContent className="flex flex-col gap-3 pt-4">
          <CreatePortfolio onCreated={setSel} />
          {list.data && list.data.length > 1 ? (
            <div className="flex items-center gap-2">
              <Label htmlFor="pf-select">Portfolio</Label>
              <Select
                id="pf-select"
                className="w-56"
                value={current ?? ''}
                onChange={(e) => setSel(e.target.value)}
              >
                {list.data.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </Select>
            </div>
          ) : null}
        </CardContent>
      </Card>
      {list.isError ? <ErrorView error={list.error} /> : null}
      {list.isLoading ? <Skeleton className="h-32 w-full" /> : null}
      {current ? <PortfolioView key={current} id={current} onDeleted={() => setSel(null)} /> : null}
      {list.data && !list.data.length ? (
        <p className="text-muted-foreground text-sm">No portfolios yet.</p>
      ) : null}
    </div>
  );
}

export default function PortfolioPage() {
  return (
    <RequireAuth>
      <PageHeader title="Portfolio" description="Paper portfolios valued at stored historical prices." />
      <Portfolios />
    </RequireAuth>
  );
}
