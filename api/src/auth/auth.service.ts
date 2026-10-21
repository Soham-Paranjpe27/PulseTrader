import { ConflictException, Injectable, UnauthorizedException } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { JwtService } from '@nestjs/jwt';
import { hash, verify } from '@node-rs/argon2';
import { User } from '@prisma/client';
import { createHash, randomBytes } from 'node:crypto';
import { AuditService } from '../audit/audit.service';
import { PrismaService } from '../prisma/prisma.service';

export interface Tokens {
  access: string;
  refresh: string;
  csrf: string;
  refreshExpires: Date;
}

const sha256 = (s: string) => createHash('sha256').update(s).digest('hex');
// argon2id with OWASP-recommended minimums
const ARGON = { memoryCost: 19456, timeCost: 2, parallelism: 1 };

export function publicUser(u: User) {
  return { id: u.id, email: u.email, name: u.name, role: u.role, createdAt: u.createdAt };
}

@Injectable()
export class AuthService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly jwt: JwtService,
    private readonly config: ConfigService,
    private readonly audit: AuditService,
  ) {}

  async register(email: string, password: string, name: string | undefined, ip?: string): Promise<User> {
    const normalized = email.trim().toLowerCase();
    if (await this.prisma.user.findUnique({ where: { email: normalized } })) {
      throw new ConflictException('an account with this email already exists');
    }
    const user = await this.prisma.user.create({
      data: { email: normalized, name, passwordHash: await hash(password, ARGON) },
    });
    await this.audit.record('auth.register', { userId: user.id, entity: 'User', entityId: user.id, ip });
    return user;
  }

  async login(
    email: string,
    password: string,
    meta: { ip?: string; userAgent?: string },
  ): Promise<{ user: User; tokens: Tokens }> {
    const user = await this.prisma.user.findUnique({ where: { email: email.trim().toLowerCase() } });
    // verify against a dummy hash when the user is unknown so timing does not reveal accounts
    const ok = user
      ? await verify(user.passwordHash, password)
      : await verify(DUMMY_HASH, password).then(() => false);
    if (!user || !ok) {
      await this.audit.record('auth.login_failed', {
        userId: user?.id,
        ip: meta.ip,
        detail: { email: email.slice(0, 254) },
      });
      throw new UnauthorizedException('invalid email or password');
    }
    const tokens = await this.issue(user, meta);
    await this.audit.record('auth.login', { userId: user.id, ip: meta.ip });
    return { user, tokens };
  }

  async refresh(
    refreshToken: string | undefined,
    meta: { ip?: string; userAgent?: string },
  ): Promise<{ user: User; tokens: Tokens }> {
    if (!refreshToken) throw new UnauthorizedException('no refresh token');
    const session = await this.prisma.session.findUnique({
      where: { refreshTokenHash: sha256(refreshToken) },
      include: { user: true },
    });
    if (!session || session.revokedAt || session.expiresAt < new Date()) {
      if (session && session.revokedAt) {
        // reuse of a rotated token: revoke every session of this user
        await this.prisma.session.updateMany({
          where: { userId: session.userId, revokedAt: null },
          data: { revokedAt: new Date() },
        });
        await this.audit.record('auth.refresh_reuse_detected', { userId: session.userId, ip: meta.ip });
      }
      throw new UnauthorizedException('session expired or revoked');
    }
    await this.prisma.session.update({ where: { id: session.id }, data: { revokedAt: new Date() } });
    return { user: session.user, tokens: await this.issue(session.user, meta) };
  }

  async logout(refreshToken: string | undefined, userId?: string, ip?: string): Promise<void> {
    if (refreshToken) {
      await this.prisma.session.updateMany({
        where: { refreshTokenHash: sha256(refreshToken), revokedAt: null },
        data: { revokedAt: new Date() },
      });
    }
    await this.audit.record('auth.logout', { userId, ip });
  }

  private async issue(user: User, meta: { ip?: string; userAgent?: string }): Promise<Tokens> {
    const ttl = this.config.getOrThrow<number>('ACCESS_TOKEN_TTL_SECONDS');
    const access = await this.jwt.signAsync(
      { sub: user.id, email: user.email, role: user.role, typ: 'access' },
      { expiresIn: ttl },
    );
    const refresh = randomBytes(32).toString('base64url');
    const days = this.config.getOrThrow<number>('REFRESH_TOKEN_TTL_DAYS');
    const refreshExpires = new Date(Date.now() + days * 86_400_000);
    await this.prisma.session.create({
      data: {
        userId: user.id,
        refreshTokenHash: sha256(refresh),
        userAgent: meta.userAgent?.slice(0, 300),
        ip: meta.ip,
        expiresAt: refreshExpires,
      },
    });
    return { access, refresh, csrf: randomBytes(24).toString('base64url'), refreshExpires };
  }
}

// argon2id hash of a random throwaway password, used only to equalise login timing
const DUMMY_HASH =
  '$argon2id$v=19$m=19456,t=2,p=1$Z/v9cSJbwKdcati4ANjL1A$UzZigOKFEIMz0igCP+TipEdoNOm3hhfLxjrprITJnbg';
