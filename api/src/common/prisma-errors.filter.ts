import {
  ArgumentsHost,
  Catch,
  ConflictException,
  HttpException,
  Logger,
  NotFoundException,
  ServiceUnavailableException,
} from '@nestjs/common';
import { BaseExceptionFilter } from '@nestjs/core';
import { Prisma } from '@prisma/client';

// connection-level codes: server unreachable, connect/handshake timeout, connection closed, pool timeout
const UNAVAILABLE = new Set(['P1001', 'P1002', 'P1008', 'P1017', 'P2024']);

type PrismaError = Prisma.PrismaClientKnownRequestError | Prisma.PrismaClientInitializationError;

/**
 * Database errors that are not the server's fault become clear client answers instead of 500s:
 * unique violation from concurrent creates (P2002) -> 409, record not found (P2025) -> 404, database
 * unreachable -> 503 DATABASE_UNAVAILABLE (the API keeps running and recovers when it is back).
 * Everything else goes to Nest's default handler (logged, 500).
 */
export function mapPrismaError(e: PrismaError): HttpException | null {
  if (e instanceof Prisma.PrismaClientInitializationError || UNAVAILABLE.has(e.code))
    return new ServiceUnavailableException({
      code: 'DATABASE_UNAVAILABLE',
      message: 'The database is not reachable. Try again shortly.',
    });
  if (e.code === 'P2002') return new ConflictException('this record already exists');
  if (e.code === 'P2025') return new NotFoundException('record not found');
  return null;
}

@Catch(Prisma.PrismaClientKnownRequestError, Prisma.PrismaClientInitializationError)
export class PrismaErrorsFilter extends BaseExceptionFilter {
  private readonly log = new Logger(PrismaErrorsFilter.name);

  override catch(e: PrismaError, host: ArgumentsHost) {
    const mapped = mapPrismaError(e);
    const code = e instanceof Prisma.PrismaClientKnownRequestError ? e.code : 'init';
    if (mapped) this.log.warn(`${code} mapped to ${mapped.getStatus()}: ${e.message.split('\n').pop()}`);
    super.catch(mapped ?? e, host);
  }
}
