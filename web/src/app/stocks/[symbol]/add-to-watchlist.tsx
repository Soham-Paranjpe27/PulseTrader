'use client';

import Link from 'next/link';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Select } from '@/components/ui/input';
import { useMe } from '@/hooks/auth';
import { ApiError, get, post } from '@/lib/api';
import type { Watchlist } from '@/lib/types';

export function AddToWatchlist({ symbol }: { symbol: string }) {
  const me = useMe();
  const qc = useQueryClient();
  const lists = useQuery({
    queryKey: ['watchlists'],
    queryFn: () => get<Watchlist[]>('/watchlists'),
    enabled: !!me.data,
  });
  const [pick, setPick] = useState('');
  const add = useMutation({
    mutationFn: (id: string) => post(`/watchlists/${id}/items`, { symbol }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlists'] }),
  });
  if (!me.data) return null;
  const all = lists.data ?? [];
  if (!all.length)
    return (
      <Button variant="outline" size="sm" asChild>
        <Link href="/watchlist">Create a watchlist</Link>
      </Button>
    );
  const target = pick || all[0]!.id;
  const already = all.find((w) => w.id === target)?.items.some((i) => i.symbol === symbol);
  return (
    <div className="flex items-center gap-1.5">
      {all.length > 1 ? (
        <Select
          aria-label="Watchlist"
          className="h-8 w-36 text-xs"
          value={target}
          onChange={(e) => setPick(e.target.value)}
        >
          {all.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </Select>
      ) : null}
      <Button
        variant="outline"
        size="sm"
        disabled={already || add.isPending}
        onClick={() => add.mutate(target)}
      >
        {already ? 'In watchlist' : 'Add to watchlist'}
      </Button>
      {add.error ? <span className="text-destructive text-xs">{(add.error as ApiError).message}</span> : null}
    </div>
  );
}
