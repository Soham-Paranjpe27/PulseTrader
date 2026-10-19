import { expect, test } from '@playwright/test';
import { clientAddress } from '../../xff-guard.cjs';

test.describe('xff guard', () => {
  test('ignores a client-supplied X-Forwarded-For when no proxy is trusted', () => {
    expect(clientAddress('6.6.6.6', '10.0.0.5', 0)).toBe('10.0.0.5');
    expect(clientAddress(undefined, '10.0.0.5', 0)).toBe('10.0.0.5');
  });
  test('behind trusted proxies takes the address they recorded, not what the client wrote', () => {
    // client wrote 6.6.6.6, the load balancer (socket peer 10.0.0.2) appended the real 203.0.113.9
    expect(clientAddress('6.6.6.6, 203.0.113.9', '10.0.0.2', 1)).toBe('203.0.113.9');
    expect(clientAddress('', '10.0.0.2', 3)).toBe('10.0.0.2');
  });
});
