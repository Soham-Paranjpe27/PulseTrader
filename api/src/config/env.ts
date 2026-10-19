/** Environment validation. The process refuses to start with a missing or weak secret. */
export interface Env {
  NODE_ENV: string;
  PORT: number;
  DATABASE_URL: string;
  JWT_SECRET: string;
  REDIS_URL: string;
  ML_SERVICE_URL: string;
  WEB_ORIGIN: string;
  COOKIE_SECURE: boolean;
  ACCESS_TOKEN_TTL_SECONDS: number;
  REFRESH_TOKEN_TTL_DAYS: number;
}

export function validateEnv(raw: Record<string, unknown>): Env {
  const str = (k: string, fallback?: string): string => {
    const v = raw[k];
    if (typeof v === 'string' && v.length > 0) return v;
    if (fallback !== undefined) return fallback;
    throw new Error(`environment variable ${k} is required`);
  };
  const int = (k: string, fallback: number): number => {
    const v = raw[k];
    if (v === undefined || v === '') return fallback;
    const n = Number(v);
    if (!Number.isInteger(n) || n <= 0)
      throw new Error(`environment variable ${k} must be a positive integer`);
    return n;
  };
  const nodeEnv = str('NODE_ENV', 'development');
  const jwt = str('JWT_SECRET');
  if (jwt.length < 32 || /change-me/i.test(jwt)) {
    throw new Error('JWT_SECRET must be at least 32 random characters (not the .env.example placeholder)');
  }
  return {
    NODE_ENV: nodeEnv,
    PORT: int('PORT', 3001),
    DATABASE_URL: str('DATABASE_URL'),
    JWT_SECRET: jwt,
    REDIS_URL: str('REDIS_URL', 'redis://localhost:6379'),
    ML_SERVICE_URL: str('ML_SERVICE_URL', 'http://localhost:8000'),
    WEB_ORIGIN: str('WEB_ORIGIN', 'http://localhost:3000'),
    COOKIE_SECURE: str('COOKIE_SECURE', nodeEnv === 'production' ? 'true' : 'false') === 'true',
    ACCESS_TOKEN_TTL_SECONDS: int('ACCESS_TOKEN_TTL_SECONDS', 900),
    REFRESH_TOKEN_TTL_DAYS: int('REFRESH_TOKEN_TTL_DAYS', 7),
  };
}
