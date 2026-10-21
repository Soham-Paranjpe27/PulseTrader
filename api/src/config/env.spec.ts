import { validateEnv } from './env';

const base = { DATABASE_URL: 'postgresql://x', JWT_SECRET: 'a'.repeat(40) };

describe('validateEnv', () => {
  it('accepts a valid environment and fills defaults', () => {
    const e = validateEnv(base);
    expect(e.PORT).toBe(3001);
    expect(e.COOKIE_SECURE).toBe(false);
  });
  it('rejects a short or placeholder JWT secret', () => {
    expect(() => validateEnv({ ...base, JWT_SECRET: 'short' })).toThrow(/JWT_SECRET/);
    expect(() =>
      validateEnv({ ...base, JWT_SECRET: 'change-me-to-a-long-random-string-xxxxxxxx' }),
    ).toThrow();
  });
  it('requires DATABASE_URL', () => {
    expect(() => validateEnv({ JWT_SECRET: 'a'.repeat(40) })).toThrow(/DATABASE_URL/);
  });
  it('defaults secure cookies on in production', () => {
    expect(validateEnv({ ...base, NODE_ENV: 'production' }).COOKIE_SECURE).toBe(true);
  });
});
