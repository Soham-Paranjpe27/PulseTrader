/**
 * Preloaded into the Next.js server (`node -r ./xff-guard.cjs server.js`).
 *
 * Next.js passes a client-supplied X-Forwarded-For through unchanged and only fills it in when it is
 * missing, so a browser could pick its own address for the API's rate limiter and audit log. This
 * rewrites the header on every request to one address: the TCP peer, or, behind
 * WEB_TRUSTED_PROXY_HOPS trusted proxies (a load balancer in front of the web app), the address
 * those proxies recorded. Anything a client wrote further left is ignored.
 */
'use strict';
const http = require('node:http');

/** Client address from an X-Forwarded-For value, the socket peer and the number of trusted hops. */
function clientAddress(xff, remote, hops) {
  const chain = String(xff ?? '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  chain.push(remote || 'unknown');
  const n = Math.max(0, Math.floor(Number(hops) || 0));
  return chain[Math.max(0, chain.length - 1 - n)];
}

const hops = Number(process.env.WEB_TRUSTED_PROXY_HOPS ?? 0);
const emit = http.Server.prototype.emit;
http.Server.prototype.emit = function guardedEmit(event, req, ...rest) {
  if (event === 'request' && req && req.headers) {
    req.headers['x-forwarded-for'] = clientAddress(
      req.headers['x-forwarded-for'],
      req.socket?.remoteAddress,
      hops,
    );
  }
  return emit.call(this, event, req, ...rest);
};

module.exports = { clientAddress };
