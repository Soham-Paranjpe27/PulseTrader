import * as React from 'react';
import { cn } from '@/lib/utils';

export function Table({ className, ...props }: React.TableHTMLAttributes<HTMLTableElement>) {
  return (
    <div className="w-full overflow-x-auto">
      <table className={cn('w-full caption-bottom text-sm', className)} {...props} />
    </div>
  );
}

export function THead(props: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className="border-border text-muted-foreground border-b text-xs" {...props} />;
}

export function TBody(props: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className="[&_tr:last-child]:border-0" {...props} />;
}

export function TR({ className, ...props }: React.HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={cn('border-border/60 hover:bg-muted/40 border-b', className)} {...props} />;
}

export function TH({ className, ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return <th className={cn('h-9 px-3 text-left font-medium whitespace-nowrap', className)} {...props} />;
}

export function TD({ className, ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn('px-3 py-2 align-middle whitespace-nowrap', className)} {...props} />;
}
