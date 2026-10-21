import { CallHandler, ExecutionContext, Injectable, NestInterceptor } from '@nestjs/common';
import type { Request, Response } from 'express';
import { Observable, finalize, tap } from 'rxjs';

interface Sample {
  at: number; // epoch ms
  ms: number;
  route: string;
  status: number;
}

/** Quantile of a sorted array (nearest rank); null when empty. */
export function quantile(sorted: number[], q: number): number | null {
  if (!sorted.length) return null;
  return sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))];
}

/** In-memory API request latency over a sliding window (per process). */
@Injectable()
export class LatencyRecorder {
  private samples: Sample[] = [];
  readonly started = Date.now();
  private readonly max = 20_000;

  record(route: string, ms: number, status: number, at = Date.now()) {
    this.samples.push({ at, ms, route, status });
    if (this.samples.length > this.max) this.samples.splice(0, this.samples.length - this.max);
  }

  /** p50/p95/p99, request and 5xx counts over the last `windowMs`, overall and for the slowest routes. */
  summary(windowMs = 5 * 60_000, now = Date.now()) {
    const recent = this.samples.filter((s) => s.at >= now - windowMs);
    const stats = (xs: Sample[]) => {
      const ms = xs.map((s) => s.ms).sort((a, b) => a - b);
      return {
        requests: xs.length,
        errors5xx: xs.filter((s) => s.status >= 500).length,
        p50: quantile(ms, 0.5),
        p95: quantile(ms, 0.95),
        p99: quantile(ms, 0.99),
      };
    };
    const byRoute = new Map<string, Sample[]>();
    for (const s of recent) {
      const xs = byRoute.get(s.route);
      if (xs) xs.push(s);
      else byRoute.set(s.route, [s]);
    }
    const routes = [...byRoute.entries()]
      .map(([route, xs]) => ({ route, ...stats(xs) }))
      .sort((a, b) => (b.p95 ?? 0) - (a.p95 ?? 0))
      .slice(0, 10);
    return { windowSeconds: windowMs / 1000, ...stats(recent), slowestRoutes: routes };
  }
}

/** Records every HTTP request's duration under its route pattern (not the raw URL: no ids or queries). */
@Injectable()
export class LatencyInterceptor implements NestInterceptor {
  constructor(private readonly rec: LatencyRecorder) {}

  intercept(ctx: ExecutionContext, next: CallHandler): Observable<unknown> {
    if (ctx.getType() !== 'http') return next.handle();
    const req = ctx.switchToHttp().getRequest<Request>();
    const res = ctx.switchToHttp().getResponse<Response>();
    const t0 = process.hrtime.bigint();
    const route = `${req.method} ${(req.route as { path?: string } | undefined)?.path ?? 'unknown'}`;
    let failed: number | null = null; // the exception filter sets the status after this runs
    return next.handle().pipe(
      tap({
        error: (e: { getStatus?: () => number }) => {
          failed = typeof e?.getStatus === 'function' ? e.getStatus() : 500;
        },
      }),
      finalize(() => {
        if (route.endsWith('/stream')) return; // SSE connections are long-lived by design
        this.rec.record(route, Number(process.hrtime.bigint() - t0) / 1e6, failed ?? res.statusCode);
      }),
    );
  }
}
