'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { useLogout, useMe } from '@/hooks/auth';
import { cn } from '@/lib/utils';
import { FeedBadge } from './status';
import { Button } from './ui/button';

const LINKS = [
  { href: '/dashboard', label: 'Dashboard' },
  { href: '/stocks', label: 'Stocks' },
  { href: '/predictions', label: 'Predictions' },
  { href: '/watchlist', label: 'Watchlist' },
  { href: '/portfolio', label: 'Portfolio' },
  { href: '/alerts', label: 'Alerts' },
  { href: '/research', label: 'Research' },
  { href: '/monitoring', label: 'Monitoring' },
];

export function Nav() {
  const path = usePathname();
  const router = useRouter();
  const me = useMe();
  const logout = useLogout();
  return (
    <header className="border-border bg-background/85 sticky top-0 z-20 border-b backdrop-blur">
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-4 px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
          <span className="bg-primary inline-block h-2.5 w-2.5 rounded-full" aria-hidden />
          PulseTrader
        </Link>
        <nav aria-label="Main" className="flex flex-1 items-center gap-1 overflow-x-auto text-sm">
          {LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className={cn(
                'text-muted-foreground hover:bg-accent hover:text-foreground rounded-md px-2.5 py-1.5 whitespace-nowrap',
                path.startsWith(l.href) && 'bg-accent text-foreground',
              )}
            >
              {l.label}
            </Link>
          ))}
        </nav>
        <FeedBadge />
        {me.data ? (
          <div className="flex items-center gap-2">
            <Link
              href="/settings"
              className="text-muted-foreground hover:text-foreground hidden text-sm sm:inline"
              title="Settings"
            >
              {me.data.name || me.data.email}
            </Link>
            <Button
              variant="outline"
              size="sm"
              onClick={() => logout.mutate(undefined, { onSettled: () => router.push('/login') })}
            >
              Log out
            </Button>
          </div>
        ) : me.isLoading ? null : (
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" asChild>
              <Link href="/login">Log in</Link>
            </Button>
            <Button size="sm" asChild>
              <Link href="/register">Register</Link>
            </Button>
          </div>
        )}
      </div>
    </header>
  );
}
