import { Controller, Get, Module, Post, Query } from '@nestjs/common';
import { ApiTags } from '@nestjs/swagger';
import { Role } from '@prisma/client';
import { AlertsModule, AlertsService } from '../alerts/alerts.module';
import { AuditService } from '../audit/audit.service';
import { AuthUser, CurrentUser, Roles } from '../common/auth';
import { PageQuery } from '../common/pagination';
import { ModelsService } from '../models/models.service';
import { PrismaService } from '../prisma/prisma.service';

@ApiTags('admin')
@Roles(Role.ADMIN)
@Controller('admin')
export class AdminController {
  constructor(
    private readonly prisma: PrismaService,
    private readonly models: ModelsService,
    private readonly alerts: AlertsService,
    private readonly audit: AuditService,
  ) {}

  @Post('sync/registry')
  async sync(@CurrentUser() u: AuthUser) {
    const r = await this.models.sync();
    await this.audit.record('admin.sync_registry', { userId: u.id, detail: { ...r } });
    return r;
  }

  @Post('alerts/evaluate')
  async evaluate(@CurrentUser() u: AuthUser) {
    const r = await this.alerts.evaluate();
    await this.audit.record('admin.evaluate_alerts', { userId: u.id, detail: { ...r } });
    return r;
  }

  @Get('audit')
  async auditLog(@Query() q: PageQuery) {
    const rows = await this.prisma.auditLog.findMany({
      orderBy: { createdAt: 'desc' },
      skip: (q.page - 1) * q.pageSize,
      take: q.pageSize,
    });
    return { items: rows.map((r) => ({ ...r, id: r.id.toString() })) };
  }
}

@Module({ imports: [AlertsModule], controllers: [AdminController] })
export class AdminModule {}
