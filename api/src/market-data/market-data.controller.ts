import { Controller, Get, NotFoundException, Param, Query } from '@nestjs/common';
import { ApiTags } from '@nestjs/swagger';
import { Public } from '../common/auth';
import { LiveService } from '../live/live.service';
import { MarketDataService } from './market-data.service';

@ApiTags('market-data')
@Public()
@Controller('market-data')
export class MarketDataController {
  constructor(
    private readonly md: MarketDataService,
    private readonly live: LiveService,
  ) {}

  @Get('status')
  status() {
    return this.live.status();
  }

  /** Latest validated live (or replayed) 1-minute close for the symbol, with the feed state. */
  @Get(':symbol/live')
  async latest(@Param('symbol') symbol: string) {
    const p = await this.live.price(symbol.toUpperCase());
    if (!p)
      throw new NotFoundException({ code: 'DATA_UNAVAILABLE', message: 'no live price for this symbol' });
    return { symbol: symbol.toUpperCase(), ...p };
  }

  @Get(':symbol/daily')
  daily(@Param('symbol') symbol: string, @Query('from') from?: string, @Query('to') to?: string) {
    return this.md.daily(symbol.toUpperCase(), from, to);
  }

  @Get(':symbol/intraday')
  intraday(@Param('symbol') symbol: string, @Query('date') date?: string) {
    return this.md.intraday(symbol.toUpperCase(), date);
  }

  @Get(':symbol/indicators')
  indicators(@Param('symbol') symbol: string, @Query('date') date?: string) {
    return this.md.indicators(symbol.toUpperCase(), date);
  }
}
