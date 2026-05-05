/**
 * Safe UUID generator with fallback for non-secure contexts.
 *
 * Why
 * ---
 * `crypto.randomUUID()` is only exposed in *secure contexts* — HTTPS or
 * `http://localhost`. On a plain-HTTP deploy (e.g. our alpha at
 * http://20.241.146.88) the call throws `TypeError: crypto.randomUUID
 * is not a function`. That blew up the chat flow because the turn-id
 * generator runs on every question.
 *
 * Strategy
 * --------
 * 1. Use the real `crypto.randomUUID` when available (HTTPS prod path).
 * 2. Otherwise build a v4-shaped UUID from `crypto.getRandomValues`
 *    (which IS available on plain HTTP). Cryptographically equivalent.
 * 3. Last resort, `Math.random()` — only hit on really old browsers
 *    where neither API exists. Not collision-resistant, but the turn-id
 *    is purely a UI cache key — collisions just merge two turns.
 *
 * Don't use this for anything security-sensitive. For UI cache keys,
 * session IDs in URLs, etc., it's fine.
 */
export function randomUUID(): string {
  // Path 1: real WebCrypto randomUUID (HTTPS or localhost)
  if (
    typeof globalThis !== 'undefined' &&
    globalThis.crypto &&
    typeof globalThis.crypto.randomUUID === 'function'
  ) {
    return globalThis.crypto.randomUUID();
  }

  // Path 2: build v4 from getRandomValues (works on plain HTTP)
  const c = (globalThis as { crypto?: Crypto }).crypto;
  if (c && typeof c.getRandomValues === 'function') {
    const bytes = new Uint8Array(16);
    c.getRandomValues(bytes);
    // Per RFC 4122 §4.4 — set version (4) and variant (10xx) bits
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0'));
    return `${hex.slice(0, 4).join('')}-${hex.slice(4, 6).join('')}-${hex
      .slice(6, 8)
      .join('')}-${hex.slice(8, 10).join('')}-${hex.slice(10, 16).join('')}`;
  }

  // Path 3: Math.random fallback. Not for crypto, but UI cache keys are fine.
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}
