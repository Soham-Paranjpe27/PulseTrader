import { applyTrade, valuation } from './portfolio.math';

describe('paper portfolio math', () => {
  it('buys and averages cost', () => {
    const a = applyTrade(1000, null, 'BUY', 5, 100);
    expect(a.cash).toBe(500);
    const b = applyTrade(a.cash, a.holding, 'BUY', 5, 80);
    expect(b.holding).toEqual({ quantity: 10, avgPrice: 90 });
  });
  it('sells with realized P&L and closes the position', () => {
    const r = applyTrade(0, { quantity: 10, avgPrice: 90 }, 'SELL', 10, 100);
    expect(r.cash).toBe(1000);
    expect(r.holding).toBeNull();
    expect(r.realizedPnl).toBe(100);
  });
  it('refuses overspending and short selling', () => {
    expect(() => applyTrade(100, null, 'BUY', 2, 60)).toThrow(/cash/);
    expect(() => applyTrade(100, { quantity: 1, avgPrice: 1 }, 'SELL', 2, 1)).toThrow(/short/);
    expect(() => applyTrade(100, null, 'BUY', 0, 1)).toThrow();
  });
  it('values positions and flags unpriced ones', () => {
    const v = valuation(100, [
      { quantity: 2, avgPrice: 10, price: 15 },
      { quantity: 1, avgPrice: 5, price: null },
    ]);
    expect(v.marketValue).toBe(30);
    expect(v.unrealizedPnl).toBe(30 - 25);
    expect(v.unpricedPositions).toBe(1);
  });
});
