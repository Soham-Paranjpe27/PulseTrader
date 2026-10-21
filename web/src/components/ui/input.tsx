import * as React from 'react';
import { cn } from '@/lib/utils';

export function Input({ className, type, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      type={type}
      className={cn(
        'border-input placeholder:text-muted-foreground focus-visible:ring-ring flex h-9 w-full rounded-md border bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:ring-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    />
  );
}

export function Select({ className, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        'border-input bg-card focus-visible:ring-ring flex h-9 w-full rounded-md border px-2 py-1 text-sm shadow-sm focus-visible:ring-2 focus-visible:outline-none',
        className,
      )}
      {...props}
    />
  );
}

export function Textarea({ className, ...props }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={cn(
        'border-input placeholder:text-muted-foreground focus-visible:ring-ring flex min-h-16 w-full rounded-md border bg-transparent px-3 py-2 text-sm shadow-sm focus-visible:ring-2 focus-visible:outline-none',
        className,
      )}
      {...props}
    />
  );
}
