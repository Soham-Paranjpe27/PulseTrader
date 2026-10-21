'use client';

import { Button } from '@/components/ui/button';
import { Callout } from '@/components/ui/callout';

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="mx-auto mt-10 max-w-lg">
      <Callout tone="error" title="Something went wrong">
        <p className="mb-3">{error.message}</p>
        <Button size="sm" onClick={reset}>
          Try again
        </Button>
      </Callout>
    </div>
  );
}
