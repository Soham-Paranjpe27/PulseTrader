import { Global, Injectable, Logger, Module } from '@nestjs/common';
import { Prisma } from '@prisma/client';
import { PrismaService } from '../prisma/prisma.service';

/** Append-only audit trail of security-relevant and state-changing actions. */
@Injectable()
export class AuditService {
  private readonly log = new Logger(AuditService.name);

  constructor(private readonly prisma: PrismaService) {}

  async record(
    action: string,
    opts: {
      userId?: string | null;
      entity?: string;
      entityId?: string;
      ip?: string;
      detail?: Prisma.InputJsonValue;
    } = {},
  ): Promise<void> {
    try {
      await this.prisma.auditLog.create({
        data: {
          action,
          userId: opts.userId ?? null,
          entity: opts.entity,
          entityId: opts.entityId,
          ip: opts.ip,
          detail: opts.detail,
        },
      });
    } catch (e) {
      // the request itself succeeded; a failed audit write is logged loudly, not swallowed
      this.log.error(`audit write failed for ${action}: ${(e as Error).message}`);
    }
  }
}

@Global()
@Module({ providers: [AuditService], exports: [AuditService] })
export class AuditModule {}
