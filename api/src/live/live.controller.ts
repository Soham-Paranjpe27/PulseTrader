import {
  Body,
  CanActivate,
  Controller,
  ExecutionContext,
  ForbiddenException,
  Get,
  HttpCode,
  Injectable,
  Post,
  ServiceUnavailableException,
  UseGuards,
} from '@nestjs/common';
import { ApiTags } from '@nestjs/swagger';
import { SkipThrottle } from '@nestjs/throttler';
import { createHash, timingSafeEqual } from 'node:crypto';
import type { Request } from 'express';
import { Public, SkipCsrf } from '../common/auth';
import { LiveService } from './live.service';

const digest = (s: string) => createHash('sha256').update(s).digest();

/** Machine-to-machine auth for the live pipeline: `x-ingest-token` must equal LIVE_INGEST_TOKEN. */
@Injectable()
export class IngestTokenGuard implements CanActivate {
  canActivate(ctx: ExecutionContext): boolean {
    const expected = process.env.LIVE_INGEST_TOKEN ?? '';
    if (expected.length < 32) throw new ServiceUnavailableException('live ingestion is not configured');
    const got = ctx.switchToHttp().getRequest<Request>().header('x-ingest-token') ?? '';
    // compare fixed-length digests so neither length nor content leaks through timing
    if (!timingSafeEqual(digest(got), digest(expected))) throw new ForbiddenException('bad ingest token');
    return true;
  }
}

@ApiTags('live')
@Controller('live')
export class LiveController {
  constructor(private readonly live: LiveService) {}

  @Public()
  @Get('status')
  status() {
    return this.live.status();
  }

  @Public()
  @SkipCsrf()
  @SkipThrottle()
  @UseGuards(IngestTokenGuard)
  @Post('status')
  @HttpCode(200)
  setStatus(@Body() body: unknown) {
    return this.live.setStatus(body);
  }

  @Public()
  @SkipCsrf()
  @SkipThrottle()
  @UseGuards(IngestTokenGuard)
  @Post('ingest')
  @HttpCode(200)
  ingest(@Body() body: unknown) {
    return this.live.ingest(body);
  }
}
