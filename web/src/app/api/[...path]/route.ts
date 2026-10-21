import type { NextRequest } from 'next/server';
import { buildUpstreamUrl, forwardRequestHeaders, forwardResponseHeaders } from '@/lib/proxy';

/**
 * Same-origin proxy to the NestJS API (API_URL, read at runtime). The browser only ever talks to the
 * web origin, so the API's httpOnly cookies and the csrf_token cookie are first-party, and SSE streams
 * pass through unbuffered.
 */
export const dynamic = 'force-dynamic';

async function handle(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }): Promise<Response> {
  const { path } = await ctx.params;
  const target = buildUpstreamUrl(process.env.API_URL ?? 'http://localhost:3001', path, req.nextUrl.search);
  if (!target) return Response.json({ code: 'BAD_REQUEST', message: 'invalid path' }, { status: 400 });
  const method = req.method.toUpperCase();
  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method,
      headers: forwardRequestHeaders(req.headers),
      body: method === 'GET' || method === 'HEAD' ? undefined : await req.arrayBuffer(),
      redirect: 'manual',
      cache: 'no-store',
      signal: req.signal,
    });
  } catch (e) {
    console.error(`API proxy: ${target} unreachable: ${(e as Error).message}`);
    return Response.json(
      { code: 'API_UNAVAILABLE', message: 'The PulseTrader API is not reachable.' },
      { status: 502 },
    );
  }
  return new Response(upstream.body, {
    status: upstream.status,
    headers: forwardResponseHeaders(upstream.headers),
  });
}

export { handle as GET, handle as POST, handle as PATCH, handle as DELETE };
