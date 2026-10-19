'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useFeedStatus } from '@/hooks/queries';
import { useMe } from '@/hooks/auth';
import { ApiError } from '@/lib/api';
import { codeLabel, dirTone } from '@/lib/format';
import type { Direction, ModelStatus } from '@/lib/types';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Callout, Skeleton } from './ui/callout';

/** Market-data feed state from the API. Never shows LIVE unless the backend says the feed is live. */
export function FeedBadge() {
  const q = useFeedStatus();
  if (q.isLoading) return null;
  const state = q.data?.state ?? 'UNKNOWN';
  const tone = state === 'LIVE' ? 'up' : state === 'DELAYED' ? 'warn' : 'neutral';
  return (
    <Badge
      tone={q.isError ? 'down' : tone}
      title={q.data?.reason ?? (q.error as Error | null)?.message ?? ''}
      data-testid="feed-state"
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${state === 'LIVE' ? 'bg-up' : 'bg-muted-foreground'}`}
        aria-hidden
      />
      {q.isError ? 'API UNREACHABLE' : `FEED ${state}`}
    </Badge>
  );
}

export function DirectionBadge({ d }: { d: Direction | null | undefined }) {
  if (!d) return <Badge>–</Badge>;
  const arrow = d === 'UP' ? '▲ ' : d === 'DOWN' ? '▼ ' : '';
  return (
    <Badge tone={dirTone(d)} data-testid="direction">
      {arrow}
      {d === 'NO_PREDICTION' ? 'NO PREDICTION' : d}
    </Badge>
  );
}

export function ModelStatusBadge({ s }: { s: ModelStatus | string }) {
  const tone =
    s === 'PRODUCTION'
      ? 'up'
      : s === 'REJECTED' || s === 'RETIRED'
        ? 'down'
        : s === 'CANDIDATE'
          ? 'warn'
          : 'info';
  return <Badge tone={tone}>{s}</Badge>;
}

export function GateBadge({ s }: { s: string }) {
  return <Badge tone={s === 'PASSED' ? 'up' : s === 'FAILED' ? 'down' : 'neutral'}>{s}</Badge>;
}

export function ResearchOnly({ on }: { on: boolean }) {
  return on ? (
    <Badge tone="warn" title="Candidate model: not promoted to production">
      RESEARCH ONLY
    </Badge>
  ) : null;
}

/** Shows an API error with its code, e.g. TEST_PERIOD_LOCKED or DATA_UNAVAILABLE. */
export function ErrorView({ error, title }: { error: unknown; title?: string }) {
  if (!error) return null;
  const code = error instanceof ApiError ? error.code : 'ERROR';
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <Callout tone={code === 'DATA_UNAVAILABLE' ? 'neutral' : 'error'} title={title ?? codeLabel(code)}>
      <span data-testid="error-code" className="font-mono text-xs">
        {code}
      </span>
      {msg && msg !== code ? <span className="ml-2">{msg}</span> : null}
    </Callout>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description ? <p className="text-muted-foreground mt-1 text-sm">{description}</p> : null}
      </div>
      {actions}
    </div>
  );
}

/** Renders children only for a signed-in user; otherwise a prompt to log in (returns here after). */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const me = useMe();
  const path = usePathname();
  if (me.isLoading) return <Skeleton className="h-40 w-full" />;
  if (me.isError) return <ErrorView error={me.error} />;
  if (!me.data)
    return (
      <Callout tone="neutral" title="Log in required">
        <p className="mb-3">This page shows your own data.</p>
        <div className="flex gap-2">
          <Button size="sm" asChild>
            <Link href={`/login?next=${encodeURIComponent(path)}`}>Log in</Link>
          </Button>
          <Button size="sm" variant="outline" asChild>
            <Link href="/register">Register</Link>
          </Button>
        </div>
      </Callout>
    );
  return <>{children}</>;
}

export function Stat({
  label,
  value,
  sub,
  tone,
  testId,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  tone?: 'up' | 'down' | 'neutral';
  testId?: string;
}) {
  return (
    <div className="min-w-0">
      <p className="text-muted-foreground text-xs">{label}</p>
      <p
        data-testid={testId}
        className={`mt-0.5 truncate text-lg font-semibold ${tone === 'up' ? 'text-up' : tone === 'down' ? 'text-down' : ''}`}
      >
        {value}
      </p>
      {sub ? <p className="text-muted-foreground truncate text-xs">{sub}</p> : null}
    </div>
  );
}
