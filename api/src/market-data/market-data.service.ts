import { BadRequestException, HttpException, Injectable, NotFoundException } from '@nestjs/common';
import { MlClient } from '../ml/ml.client';
import { PrismaService } from '../prisma/prisma.service';

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

  /**
   * Minute bars for one session. Without `date`, the most recent stored session that the ML service
   * has minute bars for (daily bars can run a day past the minute data).
   */
  async intraday(symbol: string, date?: string) {
    return this.forSession(symbol, date, (d) => this.ml.bars(symbol, d));
  }

  /** Shared-feature-engine indicators and market regime for one session (same date rule). */
  async indicators(symbol: string, date?: string) {
    return this.forSession(symbol, date, (d) => this.ml.indicators(symbol, d));
  }

  private async forSession<T>(symbol: string, date: string | undefined, get: (d: string) => Promise<T>) {
    if (date !== undefined) {
      if (!DATE_RE.test(date)) throw new BadRequestException('date must be YYYY-MM-DD');
      return get(date);
    }
    const recent = await this.prisma.marketData.findMany({
      where: { symbol },
      orderBy: { tradeDate: 'desc' },
      take: 3,
      select: { tradeDate: true },
    });
    let last: unknown = null;
    for (const r of recent) {
      try {
        return await get(r.tradeDate.toISOString().slice(0, 10));
      } catch (e) {
        if (!(e instanceof HttpException) || e.getStatus() !== 404) throw e;
        last = e;
      }
    }
    if (last) throw last as HttpException;
    throw new NotFoundException({ code: 'DATA_UNAVAILABLE', message: `no stored sessions for ${symbol}` });
  }
}
