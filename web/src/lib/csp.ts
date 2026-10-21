/** Content-Security-Policy for pages (pure, unit-tested). Scripts need the per-request nonce. */
export function buildCsp(nonce: string, dev = false): string {
  return [
    "default-src 'self'",
    // 'strict-dynamic': scripts loaded by a nonced script (Next.js chunks) are trusted; no inline scripts
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'` + (dev ? " 'unsafe-eval'" : ''),
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join('; ');
}
