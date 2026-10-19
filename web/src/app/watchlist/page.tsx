'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import Link from 'next/link';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { ErrorView, PageHeader, RequireAuth } from '@/components/status';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/callout';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { FieldError } from '@/components/ui/label';
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/table';
import { del, get, post } from '@/lib/api';
import { day } from '@/lib/format';
import { addSymbolSchema, watchlistSchema } from '@/lib/schemas';
import type { Watchlist } from '@/lib/types';

const KEY = ['watchlists'];

function AddSymbol({ list }: { list: Watchlist }) {
  const qc = useQueryClient();
  const form = useForm<z.infer<typeof addSymbolSchema>>({
    resolver: zodResolver(addSymbolSchema),
    defaultValues: { symbol: '' },
  });
  const add = useMutation({
    mutationFn: (v: { symbol: string }) =>
      post(`/watchlists/${list.id}/items`, { symbol: v.symbol.toUpperCase() }),
    onSuccess: () => {
      form.reset();
      return qc.invalidateQueries({ queryKey: KEY });
    },
  });
  return (
    <form
      noValidate
      className="flex flex-wrap items-start gap-2"
      onSubmit={form.handleSubmit((v) => add.mutate(v))}
    >
      <div className="flex flex-col gap-1">
        <Input
          aria-label={`Add symbol to ${list.name}`}
          placeholder="Symbol, e.g. TCS"
          className="w-48"
          {...form.register('symbol')}
        />
        <FieldError message={form.formState.errors.symbol?.message} />
      </div>
      <Button size="sm" type="submit" disabled={add.isPending}>
        Add
      </Button>
      {add.error ? <ErrorView error={add.error} /> : null}
    </form>
  );
}

function ListCard({ list }: { list: Watchlist }) {
  const qc = useQueryClient();
  const removeItem = useMutation({
    mutationFn: (s: string) => del(`/watchlists/${list.id}/items/${encodeURIComponent(s)}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
  const remove = useMutation({
    mutationFn: () => del(`/watchlists/${list.id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
  return (
    <Card data-testid={`watchlist-${list.name}`}>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle>{list.name}</CardTitle>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            if (confirm(`Delete watchlist "${list.name}"?`)) remove.mutate();
          }}
        >
          Delete list
        </Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <AddSymbol list={list} />
        {list.items.length ? (
          <Table>
            <THead>
              <TR>
                <TH>Symbol</TH>
                <TH>Type</TH>
                <TH>Sector</TH>
                <TH>Data to</TH>
                <TH>Added</TH>
                <TH />
              </TR>
            </THead>
            <TBody>
              {list.items.map((i) => (
                <TR key={i.id}>
                  <TD>
                    <Link
                      className="text-primary font-medium hover:underline"
                      href={`/stocks/${encodeURIComponent(i.symbol)}`}
                    >
                      {i.symbol}
                    </Link>
                  </TD>
                  <TD>
                    <Badge>{i.stock.instrumentType}</Badge>
                  </TD>
                  <TD className="text-muted-foreground text-xs">{i.stock.sector ?? '–'}</TD>
                  <TD className="text-xs">{day(i.stock.lastDate)}</TD>
                  <TD className="text-xs">{day(i.addedAt)}</TD>
                  <TD className="text-right">
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`Remove ${i.symbol}`}
                      onClick={() => removeItem.mutate(i.symbol)}
                    >
                      Remove
                    </Button>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        ) : (
          <p className="text-muted-foreground text-sm">No symbols yet.</p>
        )}
      </CardContent>
    </Card>
  );
}

function Watchlists() {
  const qc = useQueryClient();
  const lists = useQuery({ queryKey: KEY, queryFn: () => get<Watchlist[]>('/watchlists') });
  const form = useForm<z.infer<typeof watchlistSchema>>({
    resolver: zodResolver(watchlistSchema),
    defaultValues: { name: '' },
  });
  const create = useMutation({
    mutationFn: (v: { name: string }) => post('/watchlists', v),
    onSuccess: () => {
      form.reset();
      return qc.invalidateQueries({ queryKey: KEY });
    },
  });
  return (
    <div className="flex flex-col gap-4">
      <form
        noValidate
        className="flex flex-wrap items-start gap-2"
        onSubmit={form.handleSubmit((v) => create.mutate(v))}
      >
        <div className="flex flex-col gap-1">
          <Input
            aria-label="New watchlist name"
            placeholder="New watchlist name"
            className="w-64"
            {...form.register('name')}
          />
          <FieldError message={form.formState.errors.name?.message} />
        </div>
        <Button type="submit" disabled={create.isPending}>
          Create watchlist
        </Button>
        {create.error ? <ErrorView error={create.error} /> : null}
      </form>
      {lists.isLoading ? <Skeleton className="h-32 w-full" /> : null}
      {lists.isError ? <ErrorView error={lists.error} /> : null}
      {lists.data?.map((l) => (
        <ListCard key={l.id} list={l} />
      ))}
      {lists.data && !lists.data.length ? (
        <p className="text-muted-foreground text-sm">No watchlists yet.</p>
      ) : null}
    </div>
  );
}

export default function WatchlistPage() {
  return (
    <RequireAuth>
      <PageHeader title="Watchlist" description="Your private lists of instruments." />
      <Watchlists />
    </RequireAuth>
  );
}
