import { Controller, Get, Param, Query } from '@nestjs/common';
import { ApiTags } from '@nestjs/swagger';
import { Public } from '../common/auth';
import { liveStatus, MarketDataService } from './market-data.service';

@ApiTags('market-data')
@Public()
@Controller('market-data')
export class MarketDataController {
  constructor(private readonly md: MarketDataService) {}

  @Get('status')
  status() {
    return liveStatus();
  }

  @Get(':symbol/daily')
  daily(@Param('symbol') symbol: string, @Query('from') from?: string, @Query('to') to?: string) {
    return this.md.daily(symbol.toUpperCase(), from, to);
  }

  @Get(':symbol/intraday')
  intraday(@Param('symbol') symbol: string, @Query('date') date: string) {
    return this.md.intraday(symbol.toUpperCase(), date);
  }
}
