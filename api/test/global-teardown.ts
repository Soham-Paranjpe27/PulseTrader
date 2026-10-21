import { PrismaClient } from '@prisma/client';

/** Drop only the run-specific schema created in global-setup. */
export default async function teardown(): Promise<void> {
  const schema = process.env.E2E_SCHEMA;
  const url = process.env.TEST_DATABASE_URL;
  if (!schema || !url || !/^e2e_\d+_\d+$/.test(schema)) return;
  const prisma = new PrismaClient({ datasources: { db: { url } } });
  try {
    await prisma.$executeRawUnsafe(`DROP SCHEMA IF EXISTS "${schema}" CASCADE`);
  } finally {
    await prisma.$disconnect();
  }
}
