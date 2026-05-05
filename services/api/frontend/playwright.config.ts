import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config for Compass v2.
 *
 * Tests intercept the API layer (`page.route()`), so they don't require a
 * running FastAPI backend. To run them:
 *
 *   npm run dev              # in one terminal
 *   npm run test:e2e         # in another
 *
 * In CI, `webServer` below auto-starts the dev server.
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? 'github' : 'list',
  timeout: 30_000,

  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5174',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    actionTimeout: 5_000,
    navigationTimeout: 10_000,
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: process.env.CI
    ? {
        command: 'npm run dev',
        port: 5174,
        reuseExistingServer: false,
        timeout: 60_000,
      }
    : undefined,
});
