/** Display formatting. Every missing value renders as an explicit dash, never as 0. */

const DASH = '–';
const IST = 'Asia/Kolkata';

export function num(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH;
  return v.toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function inr(v: number | null | undefined, digits = 2): string {
  return v === null || v === undefined || !Number.isFinite(v) ? DASH : `₹${num(v, digits)}`;
}

export function pct(v: number | null | undefined, digits = 1, signed = false): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH;
  const s = (v * 100).toFixed(digits);
  return `${signed && v > 0 ? '+' : ''}${s}%`;
}

export function compact(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return DASH;
  const a = Math.abs(v);
  if (a >= 1e7) return `${(v / 1e7).toFixed(2)} Cr`;
  if (a >= 1e5) return `${(v / 1e5).toFixed(2)} L`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return v.toFixed(0);
}

/** Calendar date of a stored daily bar (stored as UTC midnight). */
export function day(iso: string | null | undefined): string {
  return iso ? iso.slice(0, 10) : DASH;
}

/** Timestamp shown in IST, the exchange's clock. */
export function istTime(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return DASH;
  return `${d.toLocaleString('en-GB', {
    timeZone: IST,
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })} IST`;
}

export function dirTone(d: string | null | undefined): 'up' | 'down' | 'neutral' {
  return d === 'UP' ? 'up' : d === 'DOWN' ? 'down' : 'neutral';
}

/** Human label for codes such as NO_PREDICTION or DATA_UNAVAILABLE. */
export function codeLabel(code: string | null | undefined): string {
  if (!code) return DASH;
  return code
    .toLowerCase()
    .split('_')
    .map((w, i) => (i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w))
    .join(' ');
}
