'use client';

import Link from 'next/link';
import { istTime, pct } from '@/lib/format';
import type { Prediction } from '@/lib/types';
import { DirectionBadge, ResearchOnly } from './status';
import { Badge } from './ui/badge';
import { Table, TBody, TD, TH, THead, TR } from './ui/table';

export function PredictionsTable({ rows, showSymbol = true }: { rows: Prediction[]; showSymbol?: boolean }) {
  if (!rows.length) return <p className="text-muted-foreground text-sm">No predictions stored yet.</p>;
  return (
    <Table data-testid="predictions-table">
      <THead>
        <TR>
          {showSymbol ? <TH>Symbol</TH> : null}
          <TH>Market data (bar start)</TH>
          <TH>Direction</TH>
          <TH>Reason</TH>
          <TH className="text-right">P(up) raw</TH>
          <TH className="text-right">P(down) raw</TH>
          <TH className="text-right">Confidence</TH>
          <TH>Horizon</TH>
          <TH>Model</TH>
          <TH>Data quality</TH>
          <TH>Outcome</TH>
        </TR>
      </THead>
      <TBody>
        {rows.map((p) => (
          <TR key={p.id}>
            {showSymbol ? (
              <TD>
                <Link
                  className="text-primary font-medium hover:underline"
                  href={`/stocks/${encodeURIComponent(p.symbol)}`}
                >
                  {p.symbol}
                </Link>
              </TD>
            ) : null}
            <TD className="text-xs">{istTime(p.marketDataTimestamp)}</TD>
            <TD>
              <DirectionBadge d={p.direction} />
            </TD>
            <TD className="text-muted-foreground text-xs">{p.abstainReason ?? '–'}</TD>
            <TD className="text-right">{pct(p.rawProbability.up)}</TD>
            <TD className="text-right">{pct(p.rawProbability.down)}</TD>
            <TD className="text-right">{pct(p.confidence)}</TD>
            <TD>{p.horizonMinutes} min</TD>
            <TD className="text-xs">
              <div className="flex items-center gap-1.5">
                {p.modelVersionId} <ResearchOnly on={p.researchOnly} />
                {p.mode === 'LIVE' || p.mode === 'REPLAY' ? (
                  <Badge tone={p.mode === 'LIVE' ? 'up' : 'info'} title="made by the live pipeline">
                    {p.mode}
                  </Badge>
                ) : null}
              </div>
            </TD>
            <TD className="text-muted-foreground text-xs">{p.dataQuality}</TD>
            <TD className="text-muted-foreground text-xs">
              {p.outcome?.directionCorrect === true
                ? 'correct'
                : p.outcome?.directionCorrect === false
                  ? 'wrong'
                  : 'not evaluated'}
            </TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}

export function AccuracyGrid({
  rolling,
}: {
  rolling: Record<string, { n: number; accuracy: number | null }> | undefined;
}) {
  const keys = ['last_20', 'last_50', 'last_100', 'last_500'];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4" data-testid="recent-accuracy">
      {keys.map((k) => {
        const r = rolling?.[k];
        return (
          <div key={k} className="border-border rounded-md border p-2">
            <p className="text-muted-foreground text-xs">{k.replace('_', ' ')} calls</p>
            <p className="text-sm font-semibold">
              {r?.accuracy === null || !r ? 'DATA_UNAVAILABLE' : pct(r.accuracy)}
            </p>
            <p className="text-muted-foreground text-xs">n = {r?.n ?? 0} evaluated</p>
          </div>
        );
      })}
    </div>
  );
}
