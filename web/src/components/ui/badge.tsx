import { cva, type VariantProps } from 'class-variance-authority';
import * as React from 'react';
import { cn } from '@/lib/utils';

const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-semibold tracking-wide whitespace-nowrap',
  {
    variants: {
      tone: {
        neutral: 'border-border bg-muted text-muted-foreground',
        up: 'border-up/30 bg-up/10 text-up',
        down: 'border-down/30 bg-down/10 text-down',
        warn: 'border-warn/30 bg-warn/10 text-warn',
        info: 'border-primary/30 bg-primary/10 text-primary',
      },
    },
    defaultVariants: { tone: 'neutral' },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}
