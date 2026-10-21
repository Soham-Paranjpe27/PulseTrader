import {
  CanActivate,
  createParamDecorator,
  ExecutionContext,
  ForbiddenException,
  Injectable,
  SetMetadata,
  UnauthorizedException,
} from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import { JwtService } from '@nestjs/jwt';
import { Role } from '@prisma/client';
import type { Request } from 'express';

export const ACCESS_COOKIE = 'access_token';
export const REFRESH_COOKIE = 'refresh_token';
export const CSRF_COOKIE = 'csrf_token';
export const CSRF_HEADER = 'x-csrf-token';

export interface AuthUser {
  id: string;
  email: string;
  role: Role;
}

export interface AuthedRequest extends Request {
  user?: AuthUser;
}

const IS_PUBLIC = 'isPublic';
const SKIP_CSRF = 'skipCsrf';
/** Write route that runs before a CSRF token exists (login, register). */
export const SkipCsrf = () => SetMetadata(SKIP_CSRF, true);
const ROLES = 'roles';

/** Route needs no login. */
export const Public = () => SetMetadata(IS_PUBLIC, true);
/** Route needs one of these roles (after login). */
export const Roles = (...roles: Role[]) => SetMetadata(ROLES, roles);

export const CurrentUser = createParamDecorator((_: unknown, ctx: ExecutionContext): AuthUser => {
  const req = ctx.switchToHttp().getRequest<AuthedRequest>();
  if (!req.user) throw new UnauthorizedException();
  return req.user;
});

interface AccessPayload {
  sub: string;
  email: string;
  role: Role;
  typ: string;
}

/** Global guard: every route needs a valid access-token cookie unless marked @Public(). */
@Injectable()
export class JwtAuthGuard implements CanActivate {
  constructor(
    private readonly jwt: JwtService,
    private readonly reflector: Reflector,
  ) {}

  async canActivate(ctx: ExecutionContext): Promise<boolean> {
    const req = ctx.switchToHttp().getRequest<AuthedRequest>();
    const token: unknown = req.cookies?.[ACCESS_COOKIE];
    const isPublic = this.reflector.getAllAndOverride<boolean>(IS_PUBLIC, [ctx.getHandler(), ctx.getClass()]);
    if (typeof token === 'string' && token) {
      try {
        const p = await this.jwt.verifyAsync<AccessPayload>(token);
        if (p.typ === 'access') req.user = { id: p.sub, email: p.email, role: p.role };
      } catch (e) {
        if (!isPublic) throw new UnauthorizedException(`invalid session: ${(e as Error).message}`);
      }
    }
    if (isPublic) return true;
    if (!req.user) throw new UnauthorizedException('login required');
    const roles = this.reflector.getAllAndOverride<Role[] | undefined>(ROLES, [
      ctx.getHandler(),
      ctx.getClass(),
    ]);
    if (roles && !roles.includes(req.user.role)) throw new ForbiddenException('insufficient role');
    return true;
  }
}

const SAFE = new Set(['GET', 'HEAD', 'OPTIONS']);

/**
 * CSRF double-submit check. Auth uses cookies, so every state-changing request must echo the
 * non-httpOnly `csrf_token` cookie in the `x-csrf-token` header (a cross-site page cannot read it).
 */
@Injectable()
export class CsrfGuard implements CanActivate {
  constructor(private readonly reflector?: Reflector) {}

  canActivate(ctx: ExecutionContext): boolean {
    const req = ctx.switchToHttp().getRequest<Request>();
    if (SAFE.has(req.method)) return true;
    if (this.reflector?.getAllAndOverride<boolean>(SKIP_CSRF, [ctx.getHandler(), ctx.getClass()]))
      return true;
    const cookie: unknown = req.cookies?.[CSRF_COOKIE];
    const header = req.headers[CSRF_HEADER];
    if (typeof cookie !== 'string' || !cookie || typeof header !== 'string' || !safeEqual(cookie, header)) {
      throw new ForbiddenException('CSRF token missing or invalid');
    }
    return true;
  }
}

export function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}
