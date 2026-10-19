/**
 * Browser client for the PulseTrader API, through the same-origin /api proxy. Cookies carry the
 * session; writes echo the csrf_token cookie in x-csrf-token (double submit). A 401 triggers one
 * refresh-token rotation and a retry.
 */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/** Error body shapes from NestJS ({message, error}) or our codes ({code, message}). */
export function toApiError(status: number, body: unknown): ApiError {
  if (status === 429)
    return new ApiError(429, 'RATE_LIMITED', 'Too many attempts. Wait a minute and try again.');
  if (body && typeof body === 'object') {
    const b = body as { code?: unknown; message?: unknown; error?: unknown };
    const msg = Array.isArray(b.message)
      ? b.message.join('; ')
      : String(b.message ?? b.error ?? 'request failed');
    const code = typeof b.code === 'string' ? b.code : status === 401 ? 'UNAUTHORIZED' : `HTTP_${status}`;
    return new ApiError(status, code, msg);
  }
  return new ApiError(status, `HTTP_${status}`, typeof body === 'string' && body ? body : 'request failed');
}

export function readCookie(cookies: string, name: string): string | null {
  for (const part of cookies.split(';')) {
    const [k, ...v] = part.trim().split('=');
    if (k === name) return decodeURIComponent(v.join('='));
  }
  return null;
}

type Method = 'GET' | 'POST' | 'PATCH' | 'DELETE';

let refreshing: Promise<boolean> | null = null;

async function refresh(): Promise<boolean> {
  // no csrf cookie = never logged in on this browser (or logged out): nothing to refresh
  if (typeof document === 'undefined' || !readCookie(document.cookie, 'csrf_token')) return false;
  refreshing ??= send('POST', '/auth/refresh', {})
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

async function send(method: Method, path: string, body?: unknown): Promise<Response> {
  const headers: Record<string, string> = { accept: 'application/json' };
  if (body !== undefined) headers['content-type'] = 'application/json';
  if (method !== 'GET' && typeof document !== 'undefined') {
    const csrf = readCookie(document.cookie, 'csrf_token');
    if (csrf) headers['x-csrf-token'] = csrf;
  }
  return fetch(`/api${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin',
    cache: 'no-store',
  });
}

const NO_REFRESH = ['/auth/login', '/auth/register', '/auth/refresh', '/auth/logout'];

export async function api<T>(method: Method, path: string, body?: unknown): Promise<T> {
  let res = await send(method, path, body);
  if (res.status === 401 && !NO_REFRESH.includes(path) && (await refresh())) {
    res = await send(method, path, body);
  }
  const text = await res.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }
  if (!res.ok) throw toApiError(res.status, parsed);
  return parsed as T;
}

export const get = <T>(path: string) => api<T>('GET', path);
export const post = <T>(path: string, body?: unknown) => api<T>('POST', path, body ?? {});
export const patch = <T>(path: string, body: unknown) => api<T>('PATCH', path, body);
export const del = <T>(path: string) => api<T>('DELETE', path);

export function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params))
    if (v !== undefined && v !== null && v !== '') u.set(k, String(v));
  const s = u.toString();
  return s ? `?${s}` : '';
}
