import { defineConfig, devices } from '@playwright/test';

/**
 * Two projects:
 * - unit: pure TypeScript tests next to the code (src/**\/*.test.ts), no browser.
 * - e2e: browser tests against a running stack (web :3000 -> API :3001 -> ML service :8000, real
 *   PostgreSQL seeded with real data). Start the stack first; see docs/frontend.md.
 */
export default defineConfig({
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? 'list' : [['list'], ['html', { open: 'never' }]],
  projects: [
    { name: 'unit', testDir: './src', testMatch: '**/*.test.ts' },
    {
      name: 'e2e',
      testDir: './e2e',
      timeout: 60_000,
      retries: process.env.CI ? 1 : 0,
      workers: 1,
      use: {
        ...devices['Desktop Chrome'],
        locale: 'en-IN',
        timezoneId: 'Asia/Kolkata',
        baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:3000',
        trace: 'retain-on-failure',
        screenshot: 'only-on-failure',
        launchOptions: process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
      },
    },
  ],
});
