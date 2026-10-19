'use client';

import { num, pct } from '@/lib/format';
import type { Accuracy } from '@/lib/types';
import { AccuracyGrid } from './predictions-table';
import { Table, TBody, TD, TH, THead, TR } from './ui/table';

const MODE_NOTE: Record<string, string> = {
  LIVE: 'Predictions made by the live pipeline from real-time market data.',
  REPLAY: 'Recorded sessions replayed through the live pipeline. These are REPLAY results, not live ones.',
  HISTORICAL: 'Predictions users requested on stored historical bars.',
  CLIENT_FEATURES: 'Predictions on client-supplied features.',
};

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="border-border rounded-md border p-2">
      <p className="text-muted-foreground text-xs">{label}</p>
      <p className="text-sm font-semibold">{value}</p>
      {hint ? <p className="text-muted-foreground text-xs">{hint}</p> : null}
    </div>
  );
}

/**
 * Live performance (spec section 48): accuracy is always shown with balanced accuracy, MCC and
 * coverage, for the served calls and for the model's argmax class on every evaluated prediction.
 */
export function PerformancePanel({
  acc,
  mode,
  model,
}: {
  acc: Accuracy | undefined;
  mode: string;
  model: string;
}) {
  const p = acc?.performance;
  if (!acc) return null;
  if (!p || !p.evaluated)
    return (
      <div className="flex flex-col gap-2">
        <AccuracyGrid rolling={acc.rolling} />
        <p className="text-muted-foreground text-xs">
          {acc.note ?? 'DATA_UNAVAILABLE: no evaluated outcomes for this selection.'}
        </p>
      </div>
    );
  const s = p.selective;
  const f = p.fullCoverage;
  return (
    <div className="flex flex-col gap-3" data-testid="performance-panel">
      <p className="text-muted-foreground text-xs" data-testid="performance-mode">
        {mode
          ? `${mode}: ${MODE_NOTE[mode] ?? ''}`
          : `All modes (${Object.entries(acc.modes ?? {})
              .map(([k, v]) => `${k} ${v}`)
              .join(', ')}). Pick a mode to separate live from replayed results.`}
        {model ? '' : ' All models combined: pick a model to see one model on its own horizon.'}
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Calls (UP/DOWN)" value={String(s.calls)} hint={`coverage ${pct(s.coverage, 2)}`} />
        <Stat label="Call accuracy" value={pct(s.accuracy)} hint={`balanced ${pct(s.balancedAccuracy)}`} />
        <Stat label="Call MCC" value={num(s.mcc, 3)} hint={`${p.evaluated} evaluated`} />
        <Stat
          label="All predictions (argmax)"
          value={pct(f.accuracy)}
          hint={`balanced ${pct(f.balancedAccuracy)}, MCC ${num(f.mcc, 3)}`}
        />
        <Stat
          label="Calibration (calibrated)"
          value={`ECE ${num(p.calibrated.ece, 3)}`}
          hint={`Brier ${num(p.calibrated.brier, 3)} (raw ${num(f.brier, 3)}, ECE ${num(f.ece, 3)})`}
        />
        <Stat label="No label" value={String(p.labelUnavailable)} hint="target bar after the session close" />
      </div>
      <AccuracyGrid rolling={p.rolling} />
      <Table data-testid="daily-accuracy">
        <THead>
          <TR>
            <TH>Day (IST)</TH>
            <TH className="text-right">Evaluated</TH>
            <TH className="text-right">Calls</TH>
            <TH className="text-right">Coverage</TH>
            <TH className="text-right">Call accuracy</TH>
          </TR>
        </THead>
        <TBody>
          {p.daily
            .slice(-10)
            .reverse()
            .map((d) => (
              <TR key={d.period}>
                <TD className="text-xs">{d.period}</TD>
                <TD className="text-right">{d.evaluated}</TD>
                <TD className="text-right">{d.calls}</TD>
                <TD className="text-right">{pct(d.coverage, 2)}</TD>
                <TD className="text-right">{d.calls ? pct(d.accuracy) : '–'}</TD>
              </TR>
            ))}
        </TBody>
      </Table>
      <p className="text-muted-foreground text-xs">
        Weekly: {p.weekly.map((w) => `${w.period} ${w.calls} calls ${pct(w.accuracy)}`).join(', ')}. Monthly:{' '}
        {p.monthly.map((w) => `${w.period} ${w.calls} calls ${pct(w.accuracy)}`).join(', ')}.
        {p.truncated ? ` Computed over the latest ${p.window} evaluated predictions (whole days only).` : ''}{' '}
        A call is correct only when the realised class equals it; a NEUTRAL outcome counts as wrong.
      </p>
    </div>
  );
}
