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
  Patch,
  Post,
} from '@nestjs/common';
import { ApiProperty, ApiPropertyOptional, ApiTags } from '@nestjs/swagger';
import { AlertCondition, AlertStatus } from '@prisma/client';
import { Type } from 'class-transformer';
import { IsEnum, IsNumber, IsOptional, IsPositive, IsString, Matches } from 'class-validator';
import { AuditService } from '../audit/audit.service';
import { AuthUser, CurrentUser } from '../common/auth';
import { SYMBOL_RE } from '../common/pagination';
import { PrismaService } from '../prisma/prisma.service';
import { alertFires } from './alerts.service';

class CreateAlertDto {
  @ApiProperty() @IsString() @Matches(SYMBOL_RE) symbol: string;
  @ApiProperty({ enum: AlertCondition }) @IsEnum(AlertCondition) condition: AlertCondition;
  @ApiPropertyOptional() @IsOptional() @Type(() => Number) @IsNumber() @IsPositive() threshold?: number;
}

class UpdateAlertDto {
  @ApiProperty({ enum: [AlertStatus.ACTIVE, AlertStatus.DISABLED] }) @IsEnum(AlertStatus) status: AlertStatus;
}

@Injectable()
export class AlertsService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly audit: AuditService,
  ) {}

  list(userId: string) {
    return this.prisma.alert.findMany({ where: { userId }, orderBy: { createdAt: 'desc' } });
  }

  async create(userId: string, dto: CreateAlertDto) {
    const symbol = dto.symbol.toUpperCase();
    const price = dto.condition === 'PRICE_ABOVE' || dto.condition === 'PRICE_BELOW';
    if (price && dto.threshold === undefined) throw new BadRequestException('price alerts need a threshold');
    if (!(await this.prisma.stock.findUnique({ where: { symbol } }))) {
      throw new NotFoundException({ code: 'DATA_UNAVAILABLE', message: `unknown symbol ${symbol}` });
    }
    const a = await this.prisma.alert.create({
      data: { userId, symbol, condition: dto.condition, threshold: price ? dto.threshold : null },
    });
    await this.audit.record('alert.create', { userId, entity: 'Alert', entityId: a.id });
    return a;
  }

  async update(userId: string, id: string, status: AlertStatus) {
    if (status === AlertStatus.TRIGGERED) throw new BadRequestException('TRIGGERED is set by the evaluator');
    const r = await this.prisma.alert.updateMany({ where: { id, userId }, data: { status } });
    if (!r.count) throw new NotFoundException('alert not found');
    return this.prisma.alert.findUniqueOrThrow({ where: { id } });
  }

  async remove(userId: string, id: string) {
    const r = await this.prisma.alert.deleteMany({ where: { id, userId } });
    if (!r.count) throw new NotFoundException('alert not found');
    return { ok: true };
  }

  /** Check every ACTIVE alert against the latest stored close and latest prediction. */
  async evaluate(): Promise<{ checked: number; triggered: number }> {
    const active = await this.prisma.alert.findMany({ where: { status: AlertStatus.ACTIVE } });
    let triggered = 0;
    for (const a of active) {
      const [bar, pred] = await Promise.all([
        this.prisma.marketData.findFirst({ where: { symbol: a.symbol }, orderBy: { tradeDate: 'desc' } }),
        this.prisma.prediction.findFirst({
          where: { symbol: a.symbol },
          orderBy: { predictionTimestamp: 'desc' },
        }),
      ]);
      if (alertFires(a, { lastClose: bar?.close ?? null, latestDirection: pred?.direction ?? null })) {
        await this.prisma.alert.update({
          where: { id: a.id },
          data: { status: AlertStatus.TRIGGERED, triggeredAt: new Date() },
        });
        triggered++;
      }
    }
    return { checked: active.length, triggered };
  }
}

@ApiTags('alerts')
@Controller('alerts')
export class AlertsController {
  constructor(private readonly svc: AlertsService) {}

  @Get() list(@CurrentUser() u: AuthUser) {
    return this.svc.list(u.id);
  }

  @Post() create(@CurrentUser() u: AuthUser, @Body() dto: CreateAlertDto) {
    return this.svc.create(u.id, dto);
  }

  @Patch(':id') update(@CurrentUser() u: AuthUser, @Param('id') id: string, @Body() dto: UpdateAlertDto) {
    return this.svc.update(u.id, id, dto.status);
  }

  @Delete(':id') remove(@CurrentUser() u: AuthUser, @Param('id') id: string) {
    return this.svc.remove(u.id, id);
  }
}

@Module({ controllers: [AlertsController], providers: [AlertsService], exports: [AlertsService] })
export class AlertsModule {}
