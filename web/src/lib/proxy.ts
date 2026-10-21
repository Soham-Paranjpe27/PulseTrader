/** Helpers for the same-origin API proxy (pure, unit-tested). */

const REQUEST_HEADERS = ['accept', 'content-type', 'cookie', 'x-csrf-token', 'user-agent', 'last-event-id'];
const RESPONSE_HEADERS = ['content-type', 'cache-control', 'x-request-id', 'retry-after'];
// path params arrive decoded; '/' and control characters are rejected
const SEGMENT_RE = /^[A-Za-z0-9@._~&: ()-]+$/;

/** Upstream URL for /api/<path>; null when a segment could escape the /api prefix. */
export function buildUpstreamUrl(base: string, path: string[], search: string): string | null {
  if (!path.length) return null;
  for (const seg of path) {
    if (seg === '.' || seg === '..' || !SEGMENT_RE.test(seg)) return null;
  }
  const encoded = path.map((s) => encodeURIComponent(s)).join('/');
  return `${base.replace(/\/$/, '')}/api/${encoded}${search}`;
}

export function forwardRequestHeaders(incoming: Headers): Headers {
  const out = new Headers();
  for (const h of REQUEST_HEADERS) {
    const v = incoming.get(h);
    if (v) out.set(h, v);
  }
  // client address for the API's rate limiter / audit log (API trusts one proxy hop: TRUST_PROXY)
  const fwd = incoming.get('x-forwarded-for');
  if (fwd) out.set('x-forwarded-for', fwd);
  return out;
}

export function forwardResponseHeaders(upstream: Headers): Headers {
  const out = new Headers();
  for (const h of RESPONSE_HEADERS) {
    const v = upstream.get(h);
    if (v) out.set(h, v);
  }
  for (const c of upstream.getSetCookie()) out.append('set-cookie', c);
  if (upstream.get('content-type')?.startsWith('text/event-stream')) {
    out.set('cache-control', 'no-cache, no-transform');
    out.set('x-accel-buffering', 'no');
  }
  return out;
}
