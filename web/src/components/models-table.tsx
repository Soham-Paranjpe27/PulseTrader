'use client';

import { useModels } from '@/hooks/queries';
import { pct, num } from '@/lib/format';
import { ErrorView, GateBadge, ModelStatusBadge } from './status';
import { Skeleton } from './ui/callout';
import { Table, TBody, TD, TH, THead, TR } from './ui/table';

const GATES = [
  'no_leakage',
  'validation_passed',
  'walk_forward_passed',
  'calibration_passed',
  'backtest_passed',
  'test_passed',
  'shadow_passed',
];

/** Registry models with the measured validation metrics (accuracy always next to BA, MCC, coverage). */
export function ModelsTable({ showGates = false }: { showGates?: boolean }) {
  const q = useModels();
  if (q.isLoading) return <Skeleton className="h-24 w-full" />;
  if (q.isError) return <ErrorView error={q.error} />;
  const rows = q.data ?? [];
  if (!rows.length) return <p className="text-muted-foreground text-sm">No models registered.</p>;
  return (
    <Table data-testid="models-table">
      <THead>
        <TR>
          <TH>Model</TH>
          <TH>Status</TH>
          <TH>Accuracy gate</TH>
          <TH className="text-right">Val. accuracy</TH>
          <TH className="text-right">Balanced acc.</TH>
          <TH className="text-right">MCC</TH>
          <TH className="text-right">Coverage</TH>
          <TH className="text-right">Gated backtest, after costs</TH>
          {showGates ? GATES.map((g) => <TH key={g}>{g.replace('_passed', '').replace('_', ' ')}</TH>) : null}
        </TR>
      </THead>
      <TBody>
        {rows.map((m) => {
          const v = m.metrics.validation ?? {};
          const bt = m.backtestMetrics.gated_after_costs ?? {};
          return (
            <TR key={m.id}>
              <TD>
                <div className="font-medium">{m.modelId}</div>
                <div className="text-muted-foreground text-xs">
                  v{m.version} · {m.task} · {m.featureVersion}
                </div>
              </TD>
              <TD>
                <ModelStatusBadge s={m.status} />
              </TD>
              <TD className="text-xs">{m.accuracyGate}</TD>
              <TD className="text-right">{pct(v.accuracy)}</TD>
              <TD className="text-right">{pct(v.balanced_accuracy)}</TD>
              <TD className="text-right">{num(v.mcc, 3)}</TD>
              <TD className="text-right">{pct(v.coverage, 0)}</TD>
              <TD className="text-right">
                <span className={(bt.total_return ?? 0) < 0 ? 'text-down' : 'text-up'}>
                  {pct(bt.total_return, 1, true)}
                </span>
              </TD>
              {showGates
                ? GATES.map((g) => (
                    <TD key={g}>
                      <GateBadge s={m.gates[g] ?? 'NOT_RUN'} />
                    </TD>
                  ))
                : null}
            </TR>
          );
        })}
      </TBody>
    </Table>
  );
}
