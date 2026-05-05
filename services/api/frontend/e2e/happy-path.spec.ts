import { test, expect, type Page } from '@playwright/test';
import {
  LANDING_FIXTURE,
  SOURCES_HEALTH_FIXTURE,
  makeChatStream,
} from './fixtures/landing';

const SESSION_ID = 'sess_e2e_abc123';

/**
 * Mock every API endpoint the SPA calls. Done via page.route() so no real
 * FastAPI backend is required.
 */
async function mockApi(page: Page) {
  await page.route('**/auth/token', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ access_token: 'fake-jwt' }),
    })
  );

  await page.route('**/api/v1/home/landing', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(LANDING_FIXTURE),
    })
  );

  await page.route('**/api/v1/sources/health', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(SOURCES_HEALTH_FIXTURE),
    })
  );

  await page.route('**/api/v1/threads*', (route) => {
    if (route.request().method() === 'GET') {
      const url = route.request().url();
      // /threads/<id>
      if (/\/api\/v1\/threads\/[^/]+$/.test(url)) {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            id: SESSION_ID,
            title: 'Revenue by month',
            updated_at: new Date().toISOString(),
            message_count: 2,
          }),
        });
      }
      // /threads or /threads?...
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ threads: LANDING_FIXTURE.recent_threads }),
      });
    }
    return route.continue();
  });

  await page.route('**/api/v1/saved-questions*', (route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ saved_questions: [] }),
      });
    }
    if (route.request().method() === 'POST') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: '1',
          title: 'My question',
          question_text: 'q',
          scope: 'auto',
          pinned: false,
          last_run_at: null,
          last_result_preview: null,
        }),
      });
    }
    return route.continue();
  });

  // The streaming chat endpoint — emits NDJSON
  await page.route('**/api/v1/chat/stream', async (route) => {
    const body = JSON.parse(route.request().postData() || '{}');
    const sessionId = body.session_id || SESSION_ID;
    await route.fulfill({
      status: 200,
      contentType: 'application/x-ndjson',
      body: makeChatStream(sessionId, body.message || ''),
    });
  });
}

test.describe('Compass happy path', () => {
  test.beforeEach(async ({ page }) => {
    await mockApi(page);
  });

  test('home renders hero, ask box, and quick-start', async ({ page }) => {
    await page.goto('/');

    // Hero
    await expect(page.getByText('Welcome back, Gopal')).toBeVisible();
    await expect(page.getByRole('heading', { name: /Ask\..*Verify\..*Act\./ })).toBeVisible();

    // Ask box scope chips (Auto is the active default)
    await expect(page.getByRole('button', { name: 'Auto' })).toBeVisible();

    // Quick-start cards
    await expect(page.getByText('Revenue trends')).toBeVisible();
    await expect(page.getByText('Top products')).toBeVisible();
  });

  test('navigates to threads list and detail', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('link', { name: 'Threads' }).first().click();
    await expect(page).toHaveURL(/\/threads$/);
    await expect(page.getByText('Investigating churn drop')).toBeVisible();
  });

  test('ask flow: pipeline chips appear and answer renders', async ({ page }) => {
    await page.goto('/');

    const textarea = page.getByPlaceholder('Ask anything…');
    await textarea.click();
    await textarea.fill('What was the revenue trend by month?');

    // Send via the visible Send button
    await page.getByRole('button', { name: /Send/ }).click();

    // The pipeline shows at least one chip while or after streaming.
    // "Plan" / "Synthesize" appear in the chip AND the rail trace; pick first.
    await expect(page.getByText('Plan').first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/Synthesize|Query data/).first()).toBeVisible({
      timeout: 10_000,
    });

    // The synthesized answer text shows up
    await expect(page.getByText(/Revenue grew steadily/i)).toBeVisible({ timeout: 10_000 });

    // Source citation badge appears (also can be in the rail; pick first)
    await expect(page.getByText('olist_orders').first()).toBeVisible();

    // Follow-up chips
    await expect(page.getByRole('button', { name: /Why did March spike/i })).toBeVisible();

    // Evaluator score appears in the footer (can be in card + rail; pick first)
    await expect(page.getByText('4.0 / 5').first()).toBeVisible();
  });

  test('command palette opens with ⌘K and lists nav targets', async ({ page }) => {
    await page.goto('/');
    // Cmd on macOS, Ctrl elsewhere — Playwright's `Meta+K` works cross-platform
    await page.keyboard.press('Meta+K');
    await expect(
      page.getByPlaceholder('Search threads, questions, sources, pages…')
    ).toBeVisible();
    // The Go-to group should include Saved
    await expect(page.getByText('Saved questions').first()).toBeVisible();
    // Esc closes
    await page.keyboard.press('Escape');
    await expect(
      page.getByPlaceholder('Search threads, questions, sources, pages…')
    ).not.toBeVisible();
  });
});
