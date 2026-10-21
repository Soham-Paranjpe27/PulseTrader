import { ExecutionContext, ForbiddenException } from '@nestjs/common';
import { CSRF_COOKIE, CSRF_HEADER, CsrfGuard, safeEqual } from './auth';

function ctx(method: string, cookie?: string, header?: string): ExecutionContext {
  const req = {
    method,
    cookies: cookie ? { [CSRF_COOKIE]: cookie } : {},
    headers: header ? { [CSRF_HEADER]: header } : {},
  };
  return { switchToHttp: () => ({ getRequest: () => req }) } as unknown as ExecutionContext;
}

describe('CsrfGuard', () => {
  const g = new CsrfGuard();
  it('lets safe methods through', () => expect(g.canActivate(ctx('GET'))).toBe(true));
  it('requires matching cookie and header on writes', () => {
    expect(g.canActivate(ctx('POST', 'abc', 'abc'))).toBe(true);
    expect(() => g.canActivate(ctx('POST', 'abc', 'abd'))).toThrow(ForbiddenException);
    expect(() => g.canActivate(ctx('DELETE', 'abc'))).toThrow(ForbiddenException);
    expect(() => g.canActivate(ctx('PATCH'))).toThrow(ForbiddenException);
  });
  it('compares in constant time', () => {
    expect(safeEqual('a', 'a')).toBe(true);
    expect(safeEqual('a', 'ab')).toBe(false);
  });
});
