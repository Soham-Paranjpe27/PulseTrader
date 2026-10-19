import { Body, Controller, Get, MessageEvent, Param, Post, Query, Sse } from '@nestjs/common';
import { ApiPropertyOptional, ApiTags } from '@nestjs/swagger';
import { IsIn, IsOptional, IsString, MaxLength } from 'class-validator';
import { Observable } from 'rxjs';
import { AuditService } from '../audit/audit.service';
import { AuthUser, CurrentUser, Public } from '../common/auth';
import { PageQuery } from '../common/pagination';
import { BatchPredictionDto, CreatePredictionDto } from './predictions.dto';
import { PredictionsService } from './predictions.service';

class PredictionQuery extends PageQuery {
  @ApiPropertyOptional() @IsOptional() @IsString() @MaxLength(40) symbol?: string;
  @ApiPropertyOptional() @IsOptional() @IsString() @MaxLength(120) model?: string;
  @ApiPropertyOptional() @IsOptional() @IsIn(['UP', 'DOWN', 'NEUTRAL', 'NO_PREDICTION']) direction?: string;
}

@ApiTags('predictions')
@Controller('predictions')
export class PredictionsController {
  constructor(
    private readonly preds: PredictionsService,
    private readonly audit: AuditService,
  ) {}

  @Post()
  async create(@Body() dto: CreatePredictionDto, @CurrentUser() u: AuthUser) {
    const [p] = await this.preds.create([dto], u.id);
    await this.audit.record('prediction.create', { userId: u.id, entity: 'Prediction', entityId: p.id });
    return p;
  }

  @Post('batch')
  async batch(@Body() dto: BatchPredictionDto, @CurrentUser() u: AuthUser) {
    const rows = await this.preds.create(dto.items, u.id);
    await this.audit.record('prediction.batch', { userId: u.id, detail: { count: rows.length } });
    return { count: rows.length, items: rows };
  }

  @Public()
  @Get()
  list(@Query() q: PredictionQuery) {
    return this.preds.list(
      { symbol: q.symbol?.toUpperCase(), modelVersionId: q.model, direction: q.direction },
      q.page,
      q.pageSize,
    );
  }

  @Public()
  @Get('accuracy')
  accuracy(@Query('symbol') symbol?: string, @Query('model') model?: string) {
    return this.preds.accuracy(symbol?.toUpperCase(), model);
  }

  @Sse('stream')
  stream(): Observable<MessageEvent> {
    return this.preds.stream();
  }

  @Public()
  @Get(':id')
  get(@Param('id') id: string) {
    return this.preds.get(id);
  }
}
