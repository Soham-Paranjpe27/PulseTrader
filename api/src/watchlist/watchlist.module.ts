import {
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
import { IsString, Matches, MaxLength, MinLength } from 'class-validator';
import { AuditService } from '../audit/audit.service';
import { AuthUser, CurrentUser } from '../common/auth';
import { SYMBOL_RE } from '../common/pagination';
import { PrismaService } from '../prisma/prisma.service';

class CreateWatchlistDto {
  @ApiProperty() @IsString() @MinLength(1) @MaxLength(60) name: string;
}

class AddItemDto {
  @ApiProperty() @IsString() @Matches(SYMBOL_RE) symbol: string;
}

@Injectable()
export class WatchlistService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly audit: AuditService,
  ) {}

  list(userId: string) {
    return this.prisma.watchlist.findMany({
      where: { userId },
      include: { items: { include: { stock: true }, orderBy: { addedAt: 'asc' } } },
      orderBy: { createdAt: 'asc' },
    });
  }

  async create(userId: string, name: string) {
    const w = await this.prisma.watchlist.create({ data: { userId, name } });
    await this.audit.record('watchlist.create', { userId, entity: 'Watchlist', entityId: w.id });
    return w;
  }

  /** Only the owner can see or change a watchlist; others get 404, not 403, so ids do not leak. */
  async own(userId: string, id: string) {
    const w = await this.prisma.watchlist.findFirst({ where: { id, userId } });
    if (!w) throw new NotFoundException('watchlist not found');
    return w;
  }

  async remove(userId: string, id: string) {
    await this.own(userId, id);
    await this.prisma.watchlist.delete({ where: { id } });
    await this.audit.record('watchlist.delete', { userId, entity: 'Watchlist', entityId: id });
    return { ok: true };
  }

  async add(userId: string, id: string, symbol: string) {
    await this.own(userId, id);
    if (!(await this.prisma.stock.findUnique({ where: { symbol } }))) {
      throw new NotFoundException({ code: 'DATA_UNAVAILABLE', message: `unknown symbol ${symbol}` });
    }
    return this.prisma.watchlistItem.upsert({
      where: { watchlistId_symbol: { watchlistId: id, symbol } },
      create: { watchlistId: id, symbol },
      update: {},
    });
  }

  async removeItem(userId: string, id: string, symbol: string) {
    await this.own(userId, id);
    await this.prisma.watchlistItem.deleteMany({ where: { watchlistId: id, symbol } });
    return { ok: true };
  }
}

@ApiTags('watchlist')
@Controller('watchlists')
export class WatchlistController {
  constructor(private readonly svc: WatchlistService) {}

  @Get() list(@CurrentUser() u: AuthUser) {
    return this.svc.list(u.id);
  }

  @Post() create(@CurrentUser() u: AuthUser, @Body() dto: CreateWatchlistDto) {
    return this.svc.create(u.id, dto.name.trim());
  }

  @Delete(':id') remove(@CurrentUser() u: AuthUser, @Param('id') id: string) {
    return this.svc.remove(u.id, id);
  }

  @Post(':id/items') add(@CurrentUser() u: AuthUser, @Param('id') id: string, @Body() dto: AddItemDto) {
    return this.svc.add(u.id, id, dto.symbol.toUpperCase());
  }

  @Delete(':id/items/:symbol') removeItem(
    @CurrentUser() u: AuthUser,
    @Param('id') id: string,
    @Param('symbol') s: string,
  ) {
    return this.svc.removeItem(u.id, id, s.toUpperCase());
  }
}

@Module({ controllers: [WatchlistController], providers: [WatchlistService] })
export class WatchlistModule {}
