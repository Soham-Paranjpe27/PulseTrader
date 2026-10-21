import { Prisma } from '@prisma/client';
import { mapPrismaError } from './prisma-errors.filter';

const err = (code: string) => new Prisma.PrismaClientKnownRequestError('x', { code, clientVersion: 'test' });

describe('mapPrismaError', () => {
  it('maps unique violations to 409 and missing records to 404, nothing else', () => {
    expect(mapPrismaError(err('P2002'))?.getStatus()).toBe(409);
    expect(mapPrismaError(err('P2025'))?.getStatus()).toBe(404);
    expect(mapPrismaError(err('P2003'))).toBeNull();
  });
  it('maps an unreachable database to 503 DATABASE_UNAVAILABLE', () => {
    for (const c of ['P1001', 'P1017', 'P2024']) expect(mapPrismaError(err(c))?.getStatus()).toBe(503);
    const init = new Prisma.PrismaClientInitializationError("Can't reach database server", 'test');
    const m = mapPrismaError(init);
    expect(m?.getStatus()).toBe(503);
    expect(m?.getResponse()).toMatchObject({ code: 'DATABASE_UNAVAILABLE' });
  });
});
