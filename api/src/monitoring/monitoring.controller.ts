import { Controller, Get, HttpCode, Param, ParseUUIDPipe, Post, Query } from '@nestjs/common';
import { ApiTags } from '@nestjs/swagger';
import { Role } from '@prisma/client';
import { AuthUser, CurrentUser, Public, Roles } from '../common/auth';
import { MonitoringService } from './monitoring.service';

@ApiTags('monitoring')
@Controller('monitoring')
export class MonitoringController {
  constructor(private readonly mon: MonitoringService) {}

  /** Component health, latency, latest drift per model and open alerts (no user data). */
  @Public()
  @Get()
  summary() {
    return this.mon.summary();
  }

  @Get('alerts')
  alerts(@Query('open') open?: string, @Query('limit') limit?: string) {
    return this.mon.alerts(open === undefined ? undefined : open === 'true', Number(limit) || 100);
  }

  @Get('reports')
  reports(@Query('model') model?: string, @Query('limit') limit?: string) {
    return this.mon.reports(model, Number(limit) || 50);
  }

  @Roles(Role.ADMIN)
  @Post('alerts/:id/resolve')
  @HttpCode(200)
  resolve(@Param('id', new ParseUUIDPipe()) id: string, @CurrentUser() u: AuthUser) {
    return this.mon.resolveById(id, u.id);
  }

  @Roles(Role.ADMIN)
  @Post('check')
  @HttpCode(200)
  check() {
    return this.mon.check();
  }
}
