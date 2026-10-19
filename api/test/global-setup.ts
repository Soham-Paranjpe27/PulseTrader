import { execSync } from 'node:child_process';

/**
 * Each e2e run gets its own new PostgreSQL schema in the test database, created by applying the
 * migrations (`prisma migrate deploy`, non-destructive). Existing data is never reset or dropped;
 * teardown removes only the schema this run created.
 */
export default function setup(): void {
  const base = process.env.TEST_DATABASE_URL;
  if (!base) throw new Error('TEST_DATABASE_URL is required for e2e tests');
  if (base === process.env.DATABASE_URL) throw new Error('TEST_DATABASE_URL must differ from DATABASE_URL');
  const schema = `e2e_${Date.now()}_${process.pid}`;
  const url = `${base}${base.includes('?') ? '&' : '?'}schema=${schema}`;
  execSync('npx prisma migrate deploy', { env: { ...process.env, DATABASE_URL: url }, stdio: 'inherit' });
  process.env.E2E_SCHEMA = schema;
  process.env.TEST_DATABASE_URL = url;
}
