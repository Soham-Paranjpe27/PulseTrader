import { Controller, Get, Logger, Module, ServiceUnavailableException } from '@nestjs/common';
import { ApiTags } from '@nestjs/swagger';
import { SkipThrottle } from '@nestjs/throttler';
import { Public } from '../common/auth';
import { MlClient } from '../ml/ml.client';
import { PrismaService } from '../prisma/prisma.service';
import { RedisService } from '../redis/redis.service';
import { LiveService } from '../live/live.service';

@ApiTags('health')
@Public()
@SkipThrottle()
@Controller('health')
export class HealthController {
  private readonly log = new Logger(HealthController.name);

  constructor(
    private readonly prisma: PrismaService,
    private readonly redis: RedisService,
    private readonly ml: MlClient,
    private readonly liveFeed: LiveService,
  ) {}

  @Get()
  live() {
    return { status: 'ok' };
  }

  /** Ready when the database answers. Redis and the ML service are reported (degraded, not fatal). */
  @Get('ready')
  async ready() {
    let db = false;
    try {
      await this.prisma.$queryRaw`SELECT 1`;
      db = true;
    } catch (e) {
      this.log.error(`database check failed: ${(e as Error).message}`);
    }
    const redis = await this.redis.ping();
    let ml: Record<string, unknown> = { reachable: false };
    try {
      ml = { reachable: true, ...(await this.ml.ready()) };
    } catch (e) {
      ml = { reachable: false, error: (e as Error).message };
    }
    const body = { ready: db, database: db, redis, mlService: ml, marketData: await this.liveFeed.status() };
    if (!db) throw new ServiceUnavailableException(body);
    return body;
  }
}

@Module({ controllers: [HealthController] })
export class HealthModule {}
