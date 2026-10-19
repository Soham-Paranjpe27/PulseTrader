import { Controller, Get, Param, Query } from '@nestjs/common';
import { ApiPropertyOptional, ApiTags } from '@nestjs/swagger';
import { InstrumentType } from '@prisma/client';
import { Transform } from 'class-transformer';
import { IsBoolean, IsEnum, IsOptional, IsString, MaxLength } from 'class-validator';
import { Public } from '../common/auth';
import { PageQuery } from '../common/pagination';
import { StocksService } from './stocks.service';

class StockQuery extends PageQuery {
  @ApiPropertyOptional() @IsOptional() @IsString() @MaxLength(40) q?: string;
  @ApiPropertyOptional({ enum: InstrumentType }) @IsOptional() @IsEnum(InstrumentType) type?: InstrumentType;
  @ApiPropertyOptional()
  @IsOptional()
  @Transform(({ value }) => (value === 'true' ? true : value === 'false' ? false : value))
  @IsBoolean()
  universe?: boolean;
}

@ApiTags('stocks')
@Public()
@Controller('stocks')
export class StocksController {
  constructor(private readonly stocks: StocksService) {}

  @Get()
  search(@Query() q: StockQuery) {
    return this.stocks.search(q.q, q.type, q.universe, q.page, q.pageSize);
  }

  @Get(':symbol')
  detail(@Param('symbol') symbol: string) {
    return this.stocks.detail(symbol.toUpperCase());
  }
}
