#!/usr/bin/env node
/**
 * Postbuild prerender for the public marketing landing.
 *
 * Why: most crawlers execute JS, but social-card scrapers and a few search
 * engines do not. Baking /welcome into a real HTML file with rendered DOM
 * (including the JSON-LD injected at runtime by useSEO) gives:
 *   - Faster Largest Contentful Paint (no React boot wait)
 *   - 100% reliable structured-data pickup
 *   - Bing / DuckDuckGo / LinkedIn-bot friendly
 *
 * Mechanism: boot Vite preview programmatically, drive Playwright Chromium,
 * wait for hydration sentinels, snapshot the rendered DOM, write to
 * dist/welcome/index.html.
 *
 * Output paths assume host config that serves /welcome → dist/welcome/index.html
 * with SPA fallback for everything else. Most static hosts (Vercel, Netlify,
 * S3+CloudFront, Caddy) do this with a simple try-files rule.
 *
 * Skip mechanism: set PRERENDER_SKIP=1 to opt out (CI matrix, faster local
 * builds, debugging). Failures are non-fatal — a missing prerender just means
 * crawlers fall back to the SPA shell, which is still indexable.
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, '..');
const distWelcomeDir = resolve(root, 'dist', 'welcome');

if (process.env.PRERENDER_SKIP === '1') {
  console.log('[prerender] PRERENDER_SKIP=1 — skipping.');
  process.exit(0);
}

let chromium;
let preview;
try {
  ({ chromium } = await import('@playwright/test'));
  ({ preview } = await import('vite'));
} catch (err) {
  console.warn(`[prerender] dependencies missing — skipping. (${err.message})`);
  process.exit(0);
}

let server;
let exitCode = 0;
try {
  server = await preview({
    root,
    preview: { port: 0, host: '127.0.0.1', strictPort: false },
  });
  // server.resolvedUrls.local is an array like ["http://127.0.0.1:54xxx/"]
  const url = (server.resolvedUrls?.local ?? [])[0];
  if (!url) throw new Error('vite preview did not report a resolved URL');
  console.log(`[prerender] vite preview on ${url}`);

  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    userAgent:
      'Compass-Prerender/1.0 (compatible; Playwright; +https://compass.example.com)',
  });
  const page = await ctx.newPage();

  const target = new URL('/welcome', url).toString();
  console.log(`[prerender] navigating to ${target}`);
  await page.goto(target, { waitUntil: 'networkidle', timeout: 20000 });

  // Hero h1 is our hydration sentinel. If the SPA didn't boot, useSEO never
  // ran and the JSON-LD won't be present — bail rather than ship a stale shell.
  await page.waitForSelector('h1#hero-heading', { timeout: 8000 });
  await page.waitForFunction(
    () => document.querySelectorAll('script[type="application/ld+json"]').length >= 3,
    null,
    { timeout: 8000 }
  );

  const html = await page.evaluate(
    () => '<!doctype html>\n' + document.documentElement.outerHTML
  );

  await browser.close();

  mkdirSync(distWelcomeDir, { recursive: true });
  const outPath = resolve(distWelcomeDir, 'index.html');
  writeFileSync(outPath, html);

  const sizeKB = (Buffer.byteLength(html) / 1024).toFixed(1);
  const ldCount = (html.match(/application\/ld\+json/g) || []).length;
  console.log(
    `[prerender] wrote ${outPath} (${sizeKB} KB, ${ldCount} JSON-LD blocks)`
  );
} catch (err) {
  console.error('[prerender] failed:', err.message);
  exitCode = 1;
} finally {
  if (server) {
    await new Promise((res) => server.httpServer.close(() => res()));
  }
}

process.exit(exitCode);
