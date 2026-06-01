// One-off Playwright verification: drive the live alpha URL like a stakeholder.
// Loads the SPA, asks a question, waits for the streamed answer, captures
// screenshots at the key moments. Saves to /tmp/alpha-verify-*.png.

import { chromium } from '@playwright/test';

const URL = process.env.ALPHA_URL || 'http://20.241.146.88';
const QUESTION = process.env.ALPHA_QUESTION || 'What does NRR mean and how is it computed?';
const TIMEOUT_MS = 90_000;

const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 1280, height: 900 },
  colorScheme: 'dark',
  // Don't stop on the (now-fixed) cert errors / mixed content quirks
  ignoreHTTPSErrors: true,
});
const page = await ctx.newPage();

// Surface client errors so we can debug
const consoleErrors = [];
const pageErrors = [];
page.on('pageerror', (e) => {
  pageErrors.push(e.message);
  console.error('  pageerror:', e.message);
});
page.on('console', (msg) => {
  if (msg.type() === 'error') {
    consoleErrors.push(msg.text());
    console.error('  console.error:', msg.text());
  }
});

console.log(`navigating to ${URL}/`);
await page.goto(`${URL}/`, { waitUntil: 'domcontentloaded', timeout: 30_000 });

// Wait for React to hydrate and the AskBox to appear. The home page renders
// an h1 'Welcome back' or similar, then an ask textarea.
console.log('waiting for SPA hydration…');
await page.waitForSelector('textarea, input[type="text"]', { timeout: 20_000 });

// Snapshot 1: home page rendered
await page.screenshot({ path: '/tmp/alpha-verify-1-home.png', fullPage: false });
console.log('  ✓ home loaded → /tmp/alpha-verify-1-home.png');

// Find the ask textarea — there's usually exactly one on the home page
const ask = page.locator('textarea').first();
await ask.click();
await ask.fill(QUESTION);
console.log(`typed: ${QUESTION}`);

// Snapshot 2: question typed in
await page.screenshot({ path: '/tmp/alpha-verify-2-typed.png' });

// Submit. The Send button has aria-label or text 'Send'. Use the visible
// submit affordance. Keyboard Enter is also wired but Cmd/Ctrl+Enter is
// the canonical send shortcut.
await ask.press('Meta+Enter').catch(() => null);
await ask.press('Control+Enter').catch(() => null);
// Fall through: click whichever Send button is visible inside the AskBox.
const sendButton = page
  .locator('button')
  .filter({ hasText: /^Send/ })
  .first();
const sendVisible = await sendButton.isVisible().catch(() => false);
if (sendVisible) {
  await sendButton.click();
}

console.log('waiting for streamed answer…');
// Wait for the streaming chip to disappear (signals stream complete) AND
// for an answer block of >100 chars to be present in the AnswerCard.
let answerText = '';
try {
  await page.waitForFunction(
    () => {
      // Done = no "Streaming" chip visible AND answer paragraph longer than 100 chars
      const allText = document.body.textContent || '';
      const stillStreaming = /Streaming/i.test(allText);
      if (stillStreaming) return false;
      // Look for the answer markdown block — usually a div with prose-like content
      const candidates = Array.from(document.querySelectorAll('p, div, li'));
      for (const el of candidates) {
        const t = (el.textContent || '').trim();
        if (
          t.length > 100 &&
          !t.includes('What does NRR') &&
          !t.includes('Routing question') &&
          !t.startsWith('Welcome') &&
          !t.startsWith('Sources') &&
          !t.startsWith('Every answer ships') &&
          !t.startsWith('Governed answers')
        ) {
          return true;
        }
      }
      return false;
    },
    null,
    { timeout: TIMEOUT_MS }
  );
  // Grab the longest paragraph that looks like the answer.
  answerText = await page.evaluate(() => {
    const ps = Array.from(document.querySelectorAll('p, li'));
    let best = '';
    for (const el of ps) {
      const t = (el.textContent || '').trim();
      if (
        t.length > best.length &&
        t.length < 2000 &&
        t.length > 80 &&
        !t.includes('What does NRR') &&
        !t.startsWith('Welcome') &&
        !t.startsWith('Sources') &&
        !t.startsWith('Every answer') &&
        !t.startsWith('Governed answers')
      ) {
        best = t;
      }
    }
    return best;
  });
} catch (e) {
  console.error(`  ✗ no answer arrived within ${TIMEOUT_MS}ms`);
}

// Snapshot 3: answer rendered (or whatever's on screen)
await page.waitForTimeout(1500); // small settle for any final eval chip
await page.screenshot({ path: '/tmp/alpha-verify-3-answer.png', fullPage: true });
console.log('  ✓ final state captured → /tmp/alpha-verify-3-answer.png');

console.log('\n────────── result ──────────');
if (answerText) {
  console.log(`✅ ANSWER RECEIVED (${answerText.length} chars):`);
  console.log(`   ${answerText.slice(0, 280)}${answerText.length > 280 ? '…' : ''}`);
} else {
  console.log('❌ no answer received within timeout');
}
console.log(`\npage errors:    ${pageErrors.length}`);
pageErrors.forEach((e) => console.log(`   - ${e.slice(0, 200)}`));
console.log(`console errors: ${consoleErrors.length}`);
consoleErrors.slice(0, 5).forEach((e) => console.log(`   - ${e.slice(0, 200)}`));

await browser.close();
process.exit(answerText ? 0 : 1);
