import * as React from 'react';
import { cn } from '@/lib/utils';

const tones = {
  info: 'border-primary/30 bg-primary/5',
  warn: 'border-warn/40 bg-warn/5',
  error: 'border-destructive/40 bg-destructive/5',
  neutral: 'border-border bg-muted/40',
} as const;

/** Inline notice (shadcn "Alert"). Named Callout so it is not confused with price alerts. */
export function Callout({
  tone = 'info',
  title,
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement> & { tone?: keyof typeof tones; title?: string }) {
  return (
    <div
      role={tone === 'error' ? 'alert' : 'status'}
      className={cn('rounded-lg border px-4 py-3 text-sm', tones[tone], className)}
      {...props}
    >
      {title ? <p className="mb-0.5 font-semibold">{title}</p> : null}
      <div className="text-muted-foreground">{children}</div>
    </div>
  );
}

export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('bg-muted animate-pulse rounded-md', className)} {...props} />;
}
