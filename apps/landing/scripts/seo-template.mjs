#!/usr/bin/env node
/**
 * Postbuild templater for crawler-discoverable static files.
 *
 * Vite's HTML env-replace covers index.html, but `public/*` files are copied
 * verbatim. This script rewrites the placeholder origin in dist/sitemap.xml
 * and dist/robots.txt so crawlers see the real production domain.
 *
 * Reads VITE_SITE_URL from env (matching the rest of the build pipeline).
 * Falls back to the placeholder when unset, leaving the files unchanged.
 */
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const distDir = resolve(__dirname, '..', 'dist');
const placeholder = 'https://compass.example.com';
const target = (process.env.VITE_SITE_URL ?? placeholder).replace(/\/$/, '');

if (target === placeholder) {
  console.log(
    '[seo-template] VITE_SITE_URL unset — sitemap.xml + robots.txt left at placeholder.'
  );
  process.exit(0);
}

const targets = ['sitemap.xml', 'robots.txt'];
let rewrote = 0;
for (const name of targets) {
  const path = resolve(distDir, name);
  if (!existsSync(path)) {
    console.warn(`[seo-template] missing ${name} — did vite build run?`);
    continue;
  }
  const before = readFileSync(path, 'utf8');
  const after = before.replaceAll(placeholder, target);
  if (before !== after) {
    writeFileSync(path, after);
    rewrote += 1;
    console.log(`[seo-template] rewrote ${name} → ${target}`);
  }
}

if (rewrote === 0) {
  console.log('[seo-template] no substitutions made.');
}
