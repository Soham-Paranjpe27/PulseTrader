/**
 * Question parser for the research assistant. It recognises a fixed set of intents and the stock
 * symbols mentioned; anything else is UNSUPPORTED. Answers are built only from stored application
 * data (never generated text), and missing data is reported as DATA_UNAVAILABLE.
 */
export type Intent =
  | { kind: 'LATEST_PREDICTION'; symbol: string }
  | { kind: 'WHY_PREDICTION'; symbol: string }
  | { kind: 'ACCURACY'; symbol: string | null }
  | { kind: 'COMPARE'; symbols: [string, string] }
  | { kind: 'FEATURES'; symbol: string | null }
  | { kind: 'UNSUPPORTED' };

export function parseQuestion(q: string, known: Set<string>): Intent {
  const text = q.trim();
  const upper = text.toUpperCase();
  const symbols = (upper.match(/[A-Z0-9&-]{2,20}/g) ?? []).filter((t) => known.has(t));
  const uniq = [...new Set(symbols)];
  const has = (re: RegExp) => re.test(text.toLowerCase());
  if (has(/\b(compare|vs\.?|versus)\b/) && uniq.length >= 2)
    return { kind: 'COMPARE', symbols: [uniq[0], uniq[1]] };
  if (has(/\b(feature|features|influenc|drivers?)\b/)) return { kind: 'FEATURES', symbol: uniq[0] ?? null };
  if (has(/\bwhy\b/) && uniq.length) return { kind: 'WHY_PREDICTION', symbol: uniq[0] };
  if (has(/\b(accura|accurate|performance|hit rate|mcc)\b/))
    return { kind: 'ACCURACY', symbol: uniq[0] ?? null };
  if (has(/\b(predict|prediction|forecast|signal|latest)\b/) && uniq.length)
    return { kind: 'LATEST_PREDICTION', symbol: uniq[0] };
  return { kind: 'UNSUPPORTED' };
}
