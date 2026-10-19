import { Body, Controller, Get, HttpCode, Post, Req, Res } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { ApiOkResponse, ApiTags } from '@nestjs/swagger';
import { Throttle } from '@nestjs/throttler';
import type { CookieOptions, Response } from 'express';
import {
  ACCESS_COOKIE,
  AuthedRequest,
  AuthUser,
  CSRF_COOKIE,
  CurrentUser,
  Public,
  REFRESH_COOKIE,
  SkipCsrf,
} from '../common/auth';
import { PrismaService } from '../prisma/prisma.service';
import { LoginDto, RegisterDto } from './auth.dto';
import { AuthService, publicUser, Tokens } from './auth.service';

const AUTH_LIMIT = Number(process.env.AUTH_RATE_LIMIT_PER_MINUTE ?? 10);

@ApiTags('auth')
@Controller('auth')
export class AuthController {
  constructor(
    private readonly auth: AuthService,
    private readonly config: ConfigService,
    private readonly prisma: PrismaService,
  ) {}

  private base(): CookieOptions {
    return { httpOnly: true, secure: this.config.get<boolean>('COOKIE_SECURE'), sameSite: 'lax' };
  }

  private setCookies(res: Response, t: Tokens): void {
    const ttl = this.config.getOrThrow<number>('ACCESS_TOKEN_TTL_SECONDS') * 1000;
    res.cookie(ACCESS_COOKIE, t.access, { ...this.base(), path: '/', maxAge: ttl });
    res.cookie(REFRESH_COOKIE, t.refresh, { ...this.base(), path: '/api/auth', expires: t.refreshExpires });
    // readable by the web app so it can echo it in the x-csrf-token header (double submit)
    res.cookie(CSRF_COOKIE, t.csrf, {
      ...this.base(),
      httpOnly: false,
      path: '/',
      expires: t.refreshExpires,
    });
  }

  private clearCookies(res: Response): void {
    res.clearCookie(ACCESS_COOKIE, { ...this.base(), path: '/' });
    res.clearCookie(REFRESH_COOKIE, { ...this.base(), path: '/api/auth' });
    res.clearCookie(CSRF_COOKIE, { ...this.base(), httpOnly: false, path: '/' });
  }

  @Public()
  @SkipCsrf()
  @Throttle({ default: { limit: AUTH_LIMIT, ttl: 60_000 } })
  @Post('register')
  async register(@Body() dto: RegisterDto, @Req() req: AuthedRequest) {
    const user = await this.auth.register(dto.email, dto.password, dto.name, req.ip);
    return { user: publicUser(user) };
  }

  @Public()
  @SkipCsrf()
  @Throttle({ default: { limit: AUTH_LIMIT, ttl: 60_000 } })
  @Post('login')
  @HttpCode(200)
  @ApiOkResponse({ description: 'sets httpOnly access/refresh cookies and a csrf_token cookie' })
  async login(@Body() dto: LoginDto, @Req() req: AuthedRequest, @Res({ passthrough: true }) res: Response) {
    const { user, tokens } = await this.auth.login(dto.email, dto.password, {
      ip: req.ip,
      userAgent: req.headers['user-agent'],
    });
    this.setCookies(res, tokens);
    return { user: publicUser(user) };
  }

  @Public()
  @Throttle({ default: { limit: 20, ttl: 60_000 } })
  @Post('refresh')
  @HttpCode(200)
  async refresh(@Req() req: AuthedRequest, @Res({ passthrough: true }) res: Response) {
    const { user, tokens } = await this.auth.refresh(req.cookies?.[REFRESH_COOKIE] as string | undefined, {
      ip: req.ip,
      userAgent: req.headers['user-agent'],
    });
    this.setCookies(res, tokens);
    return { user: publicUser(user) };
  }

  @Public()
  @Post('logout')
  @HttpCode(200)
  async logout(@Req() req: AuthedRequest, @Res({ passthrough: true }) res: Response) {
    await this.auth.logout(req.cookies?.[REFRESH_COOKIE] as string | undefined, req.user?.id, req.ip);
    this.clearCookies(res);
    return { ok: true };
  }

  @Get('me')
  async me(@CurrentUser() u: AuthUser) {
    const user = await this.prisma.user.findUniqueOrThrow({ where: { id: u.id } });
    return { user: publicUser(user) };
  }
}
