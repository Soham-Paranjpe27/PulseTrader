import { BadRequestException, Injectable, NotFoundException } from '@nestjs/common';
import { MlClient } from '../ml/ml.client';
import { PrismaService } from '../prisma/prisma.service';

export type FeedState = 'LIVE' | 'DELAYED' | 'STALE' | 'DISCONNECTED' | 'INVALID';

/**
 * Live feed state. No authorised live provider is wired in yet (Phase 17), so the state is
 * DISCONNECTED; it is never reported LIVE just because a client is connected.
 */
export function liveStatus(): { state: FeedState; provider: string | null; reason: string } {
  const provider = process.env.MARKET_DATA_PROVIDER || null;
  return {
    state: 'DISCONNECTED',
    provider,
    reason: provider
      ? `provider ${provider} configured but the live pipeline is not running`
      : 'no live market data provider configured',
  };
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

@Injectable()
export class MarketDataService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly ml: MlClient,
  ) {}

  async daily(symbol: string, from?: string, to?: string) {
    for (const d of [from, to])
      if (d && !DATE_RE.test(d)) throw new BadRequestException('dates must be YYYY-MM-DD');
    const stock = await this.prisma.stock.findUnique({ where: { symbol } });
    if (!stock)
      throw new NotFoundException({ code: 'DATA_UNAVAILABLE', message: `unknown symbol ${symbol}` });
    const bars = await this.prisma.marketData.findMany({
      where: {
        symbol,
        tradeDate: { ...(from ? { gte: new Date(from) } : {}), ...(to ? { lte: new Date(to) } : {}) },
      },
      orderBy: { tradeDate: 'asc' },
      take: 5000,
    });
    return { symbol, count: bars.length, bars };
  }

  async intraday(symbol: string, date: string) {
    if (!DATE_RE.test(date)) throw new BadRequestException('date must be YYYY-MM-DD');
    return this.ml.bars(symbol, date);
  }
}
