import {
  BadRequestException,
  Body,
  Controller,
  Delete,
  Get,
  Injectable,
  Module,
  NotFoundException,
  Param,
  Post,
} from '@nestjs/common';
import { ApiProperty, ApiTags } from '@nestjs/swagger';
import { Type } from 'class-transformer';
import { IsIn, IsNumber, IsPositive, IsString, Matches, Max, MaxLength, MinLength } from 'class-validator';
import { AuditService } from '../audit/audit.service';
import { AuthUser, CurrentUser } from '../common/auth';
import { SYMBOL_RE } from '../common/pagination';
import { PrismaService } from '../prisma/prisma.service';
import { applyTrade, valuation } from './portfolio.math';

class CreatePortfolioDto {
  @ApiProperty() @IsString() @MinLength(1) @MaxLength(60) name: string;
  @ApiProperty({ example: 1000000 }) @Type(() => Number) @IsNumber() @IsPositive() @Max(1e12) cash: number;
}

class TradeDto {
  @ApiProperty() @IsString() @Matches(SYMBOL_RE) symbol: string;
  @ApiProperty({ enum: ['BUY', 'SELL'] }) @IsIn(['BUY', 'SELL']) side: 'BUY' | 'SELL';
  @ApiProperty() @Type(() => Number) @IsNumber() @IsPositive() @Max(1e9) quantity: number;
}

@Injectable()
export class PortfolioService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly audit: AuditService,
  ) {}

  list(userId: string) {
    return this.prisma.portfolio.findMany({ where: { userId }, orderBy: { createdAt: 'asc' } });
  }

  async create(userId: string, dto: CreatePortfolioDto) {
    const p = await this.prisma.portfolio.create({ data: { userId, name: dto.name.trim(), cash: dto.cash } });
    await this.audit.record('portfolio.create', { userId, entity: 'Portfolio', entityId: p.id });
    return p;
  }

  private async own(userId: string, id: string) {
    const p = await this.prisma.portfolio.findFirst({ where: { id, userId }, include: { positions: true } });
    if (!p) throw new NotFoundException('portfolio not found');
    return p;
  }

  private async lastClose(symbol: string) {
    return this.prisma.marketData.findFirst({ where: { symbol }, orderBy: { tradeDate: 'desc' } });
  }

  async get(userId: string, id: string) {
    const p = await this.own(userId, id);
    const priced = await Promise.all(
      p.positions.map(async (pos) => {
        const bar = await this.lastClose(pos.symbol);
        return { ...pos, price: bar?.close ?? null, priceDate: bar?.tradeDate ?? null };
      }),
    );
    return {
      ...p,
      positions: priced,
      valuation: valuation(p.cash, priced),
      pricing: 'positions valued at the latest stored daily close (historical data, not live)',
    };
  }

  async trade(userId: string, id: string, dto: TradeDto) {
    const p = await this.own(userId, id);
    const symbol = dto.symbol.toUpperCase();
    const bar = await this.lastClose(symbol);
    if (!bar) throw new NotFoundException({ code: 'DATA_UNAVAILABLE', message: `no price for ${symbol}` });
    const held = p.positions.find((x) => x.symbol === symbol) ?? null;
    let r;
    try {
      r = applyTrade(p.cash, held, dto.side, dto.quantity, bar.close);
    } catch (e) {
      throw new BadRequestException((e as Error).message);
    }
    await this.prisma.$transaction(async (tx) => {
      await tx.portfolio.update({ where: { id }, data: { cash: r.cash } });
      if (r.holding) {
        await tx.portfolioPosition.upsert({
          where: { portfolioId_symbol: { portfolioId: id, symbol } },
          create: { portfolioId: id, symbol, quantity: r.holding.quantity, avgPrice: r.holding.avgPrice },
          update: { quantity: r.holding.quantity, avgPrice: r.holding.avgPrice },
        });
      } else {
        await tx.portfolioPosition.deleteMany({ where: { portfolioId: id, symbol } });
      }
    });
    await this.audit.record('portfolio.trade', {
      userId,
      entity: 'Portfolio',
      entityId: id,
      detail: {
        symbol,
        side: dto.side,
        quantity: dto.quantity,
        price: bar.close,
        priceDate: bar.tradeDate.toISOString(),
      },
    });
    return {
      price: bar.close,
      priceDate: bar.tradeDate,
      realizedPnl: r.realizedPnl,
      portfolio: await this.get(userId, id),
    };
  }

  async remove(userId: string, id: string) {
    await this.own(userId, id);
    await this.prisma.portfolio.delete({ where: { id } });
    return { ok: true };
  }
}

@ApiTags('portfolio')
@Controller('portfolios')
export class PortfolioController {
  constructor(private readonly svc: PortfolioService) {}

  @Get() list(@CurrentUser() u: AuthUser) {
    return this.svc.list(u.id);
  }

  @Post() create(@CurrentUser() u: AuthUser, @Body() dto: CreatePortfolioDto) {
    return this.svc.create(u.id, dto);
  }

  @Get(':id') get(@CurrentUser() u: AuthUser, @Param('id') id: string) {
    return this.svc.get(u.id, id);
  }

  @Post(':id/trades') trade(@CurrentUser() u: AuthUser, @Param('id') id: string, @Body() dto: TradeDto) {
    return this.svc.trade(u.id, id, dto);
  }

  @Delete(':id') remove(@CurrentUser() u: AuthUser, @Param('id') id: string) {
    return this.svc.remove(u.id, id);
  }
}

@Module({ controllers: [PortfolioController], providers: [PortfolioService] })
export class PortfolioModule {}
