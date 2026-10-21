'use client';

import Link from 'next/link';
import { useState } from 'react';
import { ErrorView, PageHeader } from '@/components/status';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/callout';
import { Card, CardContent } from '@/components/ui/card';
import { Input, Select } from '@/components/ui/input';
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/table';
import { useStocks } from '@/hooks/queries';
import { useDebounced } from '@/hooks/use-debounced';
import { compact, day } from '@/lib/format';

export default function StocksPage() {
  const [q, setQ] = useState('');
  const [type, setType] = useState('');
  const [universe, setUniverse] = useState('');
  const [page, setPage] = useState(1);
  const dq = useDebounced(q.trim());
  const res = useStocks({
    q: dq || undefined,
    type: type || undefined,
    universe: universe || undefined,
    page,
  });
  const total = res.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / 25));
  return (
    <>
      <PageHeader
        title="Stocks"
        description="All instruments in the dataset. Research universe = the 100 liquid equities the models were trained on."
      />
      <Card>
        <CardContent className="flex flex-col gap-3 pt-4">
          <div className="flex flex-wrap gap-2">
            <Input
              aria-label="Search symbols"
              placeholder="Search symbol or name, e.g. RELIANCE"
              className="max-w-xs"
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setPage(1);
              }}
            />
            <Select
              aria-label="Instrument type"
              className="w-36"
              value={type}
              onChange={(e) => {
                setType(e.target.value);
                setPage(1);
              }}
            >
              <option value="">All types</option>
              <option value="EQUITY">Equity</option>
              <option value="ETF">ETF</option>
              <option value="INDEX">Index</option>
              <option value="OTHER">Other</option>
            </Select>
            <Select
              aria-label="Universe"
              className="w-48"
              value={universe}
              onChange={(e) => {
                setUniverse(e.target.value);
                setPage(1);
              }}
            >
              <option value="">Any universe</option>
              <option value="true">Research universe only</option>
              <option value="false">Outside research universe</option>
            </Select>
            <span className="text-muted-foreground ml-auto self-center text-xs">
              {total.toLocaleString()} results
            </span>
          </div>
          {res.isError ? <ErrorView error={res.error} /> : null}
          {res.isLoading ? (
            <Skeleton className="h-64 w-full" />
          ) : (
            <Table data-testid="stocks-table">
              <THead>
                <TR>
                  <TH>Symbol</TH>
                  <TH>Type</TH>
                  <TH>Sector</TH>
                  <TH>Universe</TH>
                  <TH className="text-right">Median daily turnover</TH>
                  <TH>Data from</TH>
                  <TH>Data to</TH>
                </TR>
              </THead>
              <TBody>
                {res.data?.items.map((s) => (
                  <TR key={s.symbol}>
                    <TD>
                      <Link
                        className="text-primary font-medium hover:underline"
                        href={`/stocks/${encodeURIComponent(s.symbol)}`}
                      >
                        {s.symbol}
                      </Link>
                      {s.name ? <div className="text-muted-foreground text-xs">{s.name}</div> : null}
                    </TD>
                    <TD>
                      <Badge>{s.instrumentType}</Badge>
                    </TD>
                    <TD className="text-muted-foreground text-xs">{s.sector ?? '–'}</TD>
                    <TD>
                      {s.inResearchUniverse ? (
                        <Badge tone="info">RESEARCH</Badge>
                      ) : (
                        <span className="text-muted-foreground text-xs">–</span>
                      )}
                    </TD>
                    <TD className="text-right">₹{compact(s.medianDailyTurnover)}</TD>
                    <TD className="text-xs">{day(s.firstDate)}</TD>
                    <TD className="text-xs">{day(s.lastDate)}</TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
          {!res.isLoading && res.data && !res.data.items.length ? (
            <p className="text-muted-foreground text-sm">No instruments match.</p>
          ) : null}
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
    </>
  );
}
