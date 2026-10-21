export interface Holding {
  quantity: number;
  avgPrice: number;
}

export interface TradeResult {
  cash: number;
  holding: Holding | null; // null when the position is closed
  realizedPnl: number;
}

/** Long-only paper trade at `price`. Throws on insufficient cash or quantity. */
export function applyTrade(
  cash: number,
  h: Holding | null,
  side: 'BUY' | 'SELL',
  qty: number,
  price: number,
): TradeResult {
  if (!(qty > 0) || !(price > 0)) throw new Error('quantity and price must be positive');
  const notional = qty * price;
  if (side === 'BUY') {
    if (notional > cash + 1e-9) throw new Error('insufficient cash');
    const q = (h?.quantity ?? 0) + qty;
    const avg = ((h?.quantity ?? 0) * (h?.avgPrice ?? 0) + notional) / q;
    return { cash: cash - notional, holding: { quantity: q, avgPrice: avg }, realizedPnl: 0 };
  }
  if (!h || qty > h.quantity + 1e-9)
    throw new Error('cannot sell more than held (no short selling in paper portfolios)');
  const left = h.quantity - qty;
  return {
    cash: cash + notional,
    holding: left > 1e-9 ? { quantity: left, avgPrice: h.avgPrice } : null,
    realizedPnl: qty * (price - h.avgPrice),
  };
}

export function valuation(
  cash: number,
  positions: { quantity: number; avgPrice: number; price: number | null }[],
) {
  let market = 0;
  let cost = 0;
  let unpriced = 0;
  for (const p of positions) {
    cost += p.quantity * p.avgPrice;
    if (p.price === null) unpriced++;
    else market += p.quantity * p.price;
  }
  return {
    cash,
    marketValue: market,
    costBasis: cost,
    unrealizedPnl: market - cost,
    equity: cash + market,
    unpricedPositions: unpriced,
  };
}
