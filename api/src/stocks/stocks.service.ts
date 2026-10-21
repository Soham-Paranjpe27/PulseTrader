import { Injectable, NotFoundException } from '@nestjs/common';
import { InstrumentType, Prisma } from '@prisma/client';
import { PrismaService } from '../prisma/prisma.service';
import { LiveService } from '../live/live.service';
import { recentAccuracy } from './accuracy';

@Injectable()
export class StocksService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly live: LiveService,
  ) {}

  async search(
    q: string | undefined,
    type: InstrumentType | undefined,
    universe: boolean | undefined,
    page: number,
    size: number,
  ) {
    const where: Prisma.StockWhereInput = {
      ...(q
        ? { OR: [{ symbol: { contains: q.toUpperCase() } }, { name: { contains: q, mode: 'insensitive' } }] }
        : {}),
      ...(type ? { instrumentType: type } : {}),
      ...(universe !== undefined ? { inResearchUniverse: universe } : {}),
    };
    const [total, rows] = await Promise.all([
      this.prisma.stock.count({ where }),
      this.prisma.stock.findMany({
        where,
        orderBy: [
          { inResearchUniverse: 'desc' },
          { medianDailyTurnover: { sort: 'desc', nulls: 'last' } },
          { symbol: 'asc' },
        ],
        skip: (page - 1) * size,
        take: size,
      }),
    ]);
    return { total, page, pageSize: size, items: rows };
  }

  async detail(symbol: string) {
    const stock = await this.prisma.stock.findUnique({ where: { symbol } });
    if (!stock)
      throw new NotFoundException({ code: 'DATA_UNAVAILABLE', message: `unknown symbol ${symbol}` });
    const bars = await this.prisma.marketData.findMany({
      where: { symbol },
      orderBy: { tradeDate: 'desc' },
      take: 2,
    });
    const [last, prev] = bars;
    const latestPrediction = await this.prisma.prediction.findFirst({
      where: { symbol },
      orderBy: { predictionTimestamp: 'desc' },
      include: { outcome: true },
    });
    return {
      stock,
      quote: last
        ? {
            tradeDate: last.tradeDate,
            close: last.close,
            open: last.open,
            high: last.high,
            low: last.low,
            volume: last.volume,
            change: prev ? last.close - prev.close : null,
            changePct: prev ? last.close / prev.close - 1 : null,
            source: last.source,
            note: 'latest stored daily bar (historical data); not a live quote',
          }
        : null,
      latestPrediction,
      recentAccuracy: await recentAccuracy(this.prisma, { symbol }),
      liveStatus: await this.live.status(),
      livePrice: await this.live.price(symbol),
    };
  }
}
