// Bundles src/**/*.test.{ts,tsx} with esbuild (already a Vite dependency) and runs them with
// Node's built-in test runner. No extra dependencies; React views are tested via server rendering.
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readdirSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { buildSync } from 'esbuild';

const find = (dir) =>
  readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? find(path) : /\.test\.tsx?$/.test(name) ? [path] : [];
  });

const entries = find('src');
const outdir = mkdtempSync(join(tmpdir(), 'analytics-web-test-'));
buildSync({
  entryPoints: entries,
  outdir,
  outbase: 'src',
  bundle: true,
  platform: 'node',
  format: 'esm',
  jsx: 'automatic',
  outExtension: { '.js': '.mjs' },
  logLevel: 'warning',
  banner: { js: "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);" },
});
const files = entries.map((file) => join(outdir, file.replace(/^src\//, '').replace(/\.tsx?$/, '.mjs')));
const result = spawnSync(process.execPath, ['--test', ...files], { stdio: 'inherit' });
process.exit(result.status ?? 1);
