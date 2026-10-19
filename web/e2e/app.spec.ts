import { expect, type Page, test } from '@playwright/test';

/**
 * End-to-end flows against the running stack with real data (no mocks): registration, login, stock
 * search, stock detail, prediction (including the test-period lock), watchlist, alerts, portfolio,
 * research assistant and logout. Each run registers a fresh user.
 */

const email = `e2e-${Date.now()}@example.com`;
const password = 'e2e-password-123';

type Cookies = Awaited<ReturnType<ReturnType<Page['context']>['cookies']>>;
let session: Cookies | null = null;

/** Logs in through the form once; later tests reuse the session cookies (the API rate-limits logins). */
async function login(page: Page) {
  if (session) {
    await page.context().addCookies(session);
    await page.goto('/dashboard');
    await expect(page.getByTestId('health')).toBeVisible();
    return;
  }
  await page.goto('/login');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Log in' }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  session = await page.context().cookies();
}

test.describe.configure({ mode: 'serial' });

test('home shows measured model metrics and honest status', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('models-table')).toContainText('CANDIDATE');
  await expect(page.getByTestId('models-table')).toContainText('NOT VERIFIED');
  // no real feed runs in tests: DISCONNECTED, or REPLAY while a recorded session is replayed; never LIVE
  await expect(page.getByTestId('feed-state')).toHaveText(
    /FEED (DISCONNECTED|REPLAY \(recorded, not live\))/,
  );
});

test('registration validates input, then creates the account', async ({ page }) => {
  await page.goto('/register');
  await page.getByLabel('Email').fill('not-an-email');
  await page.getByLabel('Password', { exact: true }).fill('short');
  await page.getByRole('button', { name: 'Create account' }).click();
  await expect(page.getByText('Enter a valid email')).toBeVisible();
  await expect(page.getByText('At least 12 characters')).toBeVisible();

  await page.getByLabel('Name (optional)').fill('E2E User');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByLabel('Confirm password').fill(password);
  await page.getByRole('button', { name: 'Create account' }).click();
  await expect(page).toHaveURL(/\/login\?registered=1/);
  await expect(page.getByText('Account created')).toBeVisible();
});

test('login rejects a wrong password and protects private pages', async ({ page }) => {
  await page.goto('/watchlist');
  await expect(page.getByText('Log in required')).toBeVisible();
  await page.goto('/login');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill('wrong-password-1');
  await page.getByRole('button', { name: 'Log in' }).click();
  await expect(page.getByText('Login failed')).toBeVisible();
  await login(page);
  await expect(page.getByTestId('health')).toContainText('Database');
  await expect(page.getByText('No production model')).toBeVisible();
  // httpOnly session cookie is not readable from page scripts; the CSRF cookie is
  const visible = await page.evaluate(() => document.cookie);
  expect(visible).toContain('csrf_token=');
  expect(visible).not.toContain('access_token=');
});

test('stock search finds real instruments', async ({ page }) => {
  await page.goto('/stocks');
  await page.getByLabel('Search symbols').fill('RELIANCE');
  const table = page.getByTestId('stocks-table');
  await expect(table.getByRole('link', { name: 'RELIANCE', exact: true })).toBeVisible();
  await page.getByLabel('Instrument type').selectOption('INDEX');
  await page.getByLabel('Search symbols').fill('NIFTY');
  await expect(table).toContainText('INDEX');
  await page.getByLabel('Search symbols').fill('');
  await page.getByLabel('Instrument type').selectOption('');
  await page.getByLabel('Search symbols').fill('RELIANCE');
  await table.getByRole('link', { name: 'RELIANCE', exact: true }).click();
  await expect(page).toHaveURL(/\/stocks\/RELIANCE/);
});

test('stock detail shows price, chart, indicators, regime and live status', async ({ page }) => {
  await login(page);
  await page.goto('/stocks/RELIANCE');
  await expect(page.getByTestId('symbol')).toHaveText('RELIANCE');
  await expect(page.getByTestId('price')).toContainText('₹');
  await expect(page.getByTestId('live-status')).toHaveText(/LIVE STATUS: (DISCONNECTED|REPLAY)/);
  await expect(page.getByText('latest stored daily close (not live)')).toBeVisible();
  const canvas = page.getByTestId('price-chart').locator('canvas').first();
  await expect(canvas).toBeVisible();
  // the chart actually drew at container size (not the 300x150 canvas default)
  await expect.poll(() => canvas.evaluate((c: HTMLCanvasElement) => c.width)).toBeGreaterThan(400);
  await expect(page.getByTestId('indicators')).toContainText('RSI 14');
  await expect(page.getByTestId('regime')).toContainText(/TREND (UP|DOWN)|DATA_UNAVAILABLE/);
  await page.getByRole('tab', { name: 'Intraday' }).click();
  await expect(page.getByText(/1-minute candles, session \d{4}-\d{2}-\d{2}/)).toBeVisible();
  await expect(page.getByTestId('market-ts')).toContainText('IST');
  await expect(page.getByTestId('recent-accuracy')).toBeVisible();
  await page.getByRole('tab', { name: 'Daily' }).click();
});

test('historical prediction runs on validation data; the test period is locked', async ({ page }) => {
  await login(page);
  await page.goto('/stocks/RELIANCE');
  await expect(page.getByLabel('Model')).not.toHaveValue('');
  await page.getByLabel('Model').selectOption({ label: 'lightgbm-y_5m_10bp-tuned@v1 (CANDIDATE)' });
  await page.getByLabel('Session (IST)').fill('2025-06-13');
  await page.getByLabel('Bar start').fill('10:30');
  await page.getByRole('button', { name: 'Run prediction' }).click();
  const pred = page.getByTestId('prediction');
  await expect(page.getByText('Just generated.')).toBeVisible();
  await expect(pred).toContainText('RESEARCH ONLY');
  await expect(pred).toContainText('lightgbm-y_5m_10bp-tuned@v1');
  await expect(pred).toContainText('features-v2');
  await expect(pred).toContainText('VALIDATED_HISTORICAL:validation');
  await expect(pred.getByTestId('direction')).toHaveText(/UP|DOWN|NO PREDICTION/);

  await page.getByLabel('Session (IST)').fill('2025-07-01');
  await page.getByRole('button', { name: 'Run prediction' }).click();
  await expect(page.getByTestId('error-code')).toHaveText('TEST_PERIOD_LOCKED');

  await page.goto('/predictions');
  await page.getByLabel('Filter by symbol').fill('RELIANCE');
  await page.getByLabel('Mode', { exact: true }).selectOption('HISTORICAL'); // replayed rows would fill the first page
  await expect(page.getByTestId('predictions-table')).toContainText('VALIDATED_HISTORICAL:validation');
});

test('live performance: replayed predictions are scored and labelled REPLAY, not live', async ({ page }) => {
  // needs a replayed session in the database (`pulsetrader live --date ...` into the API)
  await login(page);
  await page.goto('/predictions');
  await page.getByLabel('Mode', { exact: true }).selectOption('REPLAY');
  await expect(page.getByTestId('performance-mode')).toContainText('REPLAY results, not live ones');
  const panel = page.getByTestId('performance-panel');
  await expect(panel).toContainText('Call accuracy');
  await expect(panel).toContainText('balanced');
  await expect(panel).toContainText('MCC');
  await expect(panel).toContainText('coverage');
  await expect(page.getByTestId('daily-accuracy')).toContainText(/\d{4}-\d{2}-\d{2}/);
  await expect(page.getByTestId('outcome').first()).toContainText(/actual (UP|DOWN|NEUTRAL)/);
  await expect(page.getByTestId('predictions-table')).toContainText('REPLAY');
  await expect(page.getByTestId('predictions-table')).not.toContainText(/\bLIVE\b/);
});

test('watchlist: create, add from the stock page, remove', async ({ page }) => {
  await login(page);
  await page.goto('/watchlist');
  await page.getByLabel('New watchlist name').fill('Core');
  await page.getByRole('button', { name: 'Create watchlist' }).click();
  const card = page.getByTestId('watchlist-Core');
  await card.getByLabel('Add symbol to Core').fill('tcs');
  await card.getByRole('button', { name: 'Add', exact: true }).click();
  await expect(card.getByRole('link', { name: 'TCS' })).toBeVisible();
  await card.getByLabel('Add symbol to Core').fill('NOT_A_STOCK');
  await card.getByRole('button', { name: 'Add', exact: true }).click();
  await expect(card.getByTestId('error-code')).toHaveText('DATA_UNAVAILABLE');

  await page.goto('/stocks/INFY');
  await page.getByRole('button', { name: 'Add to watchlist' }).click();
  await expect(page.getByRole('button', { name: 'In watchlist' })).toBeVisible();

  await page.goto('/watchlist');
  await expect(card.getByRole('link', { name: 'INFY' })).toBeVisible();
  await card.getByRole('button', { name: 'Remove TCS' }).click();
  await expect(card.getByRole('link', { name: 'TCS' })).toHaveCount(0);
});

test('alerts: validation, create, disable, delete', async ({ page }) => {
  await login(page);
  await page.goto('/alerts?symbol=RELIANCE');
  await expect(page.getByLabel('Symbol')).toHaveValue('RELIANCE');
  await page.getByRole('button', { name: 'Create alert' }).click();
  await expect(page.getByText('Price alerts need a price', { exact: true })).toBeVisible();
  await page.getByLabel('Price (₹)').fill('5000');
  await page.getByRole('button', { name: 'Create alert' }).click();
  const table = page.getByTestId('alerts-table');
  await expect(table).toContainText('Close above ₹5,000.00');
  await expect(table).toContainText('ACTIVE');
  await table.getByRole('button', { name: 'Disable' }).click();
  await expect(table).toContainText('DISABLED');
  await table.getByRole('button', { name: 'Delete' }).click();
  await expect(page.getByText('No alerts yet.')).toBeVisible();
});

test('paper portfolio: buy at the stored close, reject overselling', async ({ page }) => {
  await login(page);
  await page.goto('/portfolio');
  await page.getByLabel('Name').fill('Paper');
  await page.getByLabel('Starting cash (₹)').fill('1000000');
  await page.getByRole('button', { name: 'Create portfolio' }).click();
  const pf = page.getByTestId('portfolio');
  await expect(pf.getByTestId('cash')).toHaveText('₹10,00,000.00');
  await pf.getByLabel('Symbol').fill('RELIANCE');
  await pf.getByLabel('Quantity').fill('10');
  await pf.getByRole('button', { name: 'Place paper trade' }).click();
  await expect(pf.getByTestId('trade-result')).toContainText('Filled at ₹');
  await expect(pf.getByTestId('positions')).toContainText('RELIANCE');
  await pf.getByLabel('Side').selectOption('SELL');
  await pf.getByLabel('Quantity').fill('11');
  await pf.getByRole('button', { name: 'Place paper trade' }).click();
  await expect(pf.getByText('Trade rejected')).toBeVisible();
  await expect(pf.getByText(/cannot sell more than held/)).toBeVisible();
});

test('research assistant answers from data or says DATA_UNAVAILABLE', async ({ page }) => {
  await login(page);
  await page.goto('/research');
  await page.getByLabel('Question').fill('What is the latest prediction for RELIANCE?');
  await page.getByRole('button', { name: 'Ask', exact: true }).click();
  await expect(page.getByTestId('answer-status').first()).toHaveText('OK');
  await expect(page.getByTestId('answer').first()).toContainText('RELIANCE');
  await page.getByRole('button', { name: 'Which features influenced the prediction for HDFCBANK?' }).click();
  await expect(page.getByTestId('answer-status').first()).toHaveText('DATA_UNAVAILABLE');
});

test('settings saves the profile; logout ends the session', async ({ page }) => {
  await login(page);
  await page.goto('/settings');
  await page.getByLabel('Display name').fill('Renamed User');
  await page.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByText('Saved')).toBeVisible();
  await page.getByLabel('Theme').selectOption('light');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await page.getByRole('main').getByRole('button', { name: 'Log out' }).click();
  await expect(page).toHaveURL(/\/login/);
  await page.goto('/portfolio');
  await expect(page.getByText('Log in required')).toBeVisible();
  const r = await page.request.get('/api/auth/me');
  expect(r.status()).toBe(401);
});
