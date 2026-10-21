import { NextResponse, type NextRequest } from 'next/server';
import { buildCsp } from '@/lib/csp';

/**
 * A fresh CSP nonce per page request. Next.js reads the nonce from the request's CSP header and puts
 * it on its own scripts; the root layout puts it on the theme script. Pages are rendered per request
 * (the layout reads headers()), so a nonce is never cached into static HTML.
 */
export function middleware(req: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString('base64');
  const csp = buildCsp(nonce, process.env.NODE_ENV === 'development');
  const headers = new Headers(req.headers);
  headers.set('x-nonce', nonce);
  headers.set('content-security-policy', csp);
  const res = NextResponse.next({ request: { headers } });
  res.headers.set('content-security-policy', csp);
  return res;
}

export const config = {
  // pages only: not the API proxy, static assets or prefetches
  matcher: [
    {
      source: '/((?!api|_next/static|_next/image|favicon.ico).*)',
      missing: [
        { type: 'header', key: 'next-router-prefetch' },
        { type: 'header', key: 'purpose', value: 'prefetch' },
      ],
    },
  ],
};
