/**
 * Thin API wrapper.
 * Dev: Vite proxies /api → http://localhost:8080.
 * Prod: same-origin requests after build is served by FastAPI.
 */

const API_BASE = '/api/v1';

let cachedToken: string | null = null;

async function getToken(): Promise<string> {
  if (cachedToken) return cachedToken;
  const res = await fetch('/auth/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: 'ui-user', role: 'admin' }),
  });
  const data = await res.json();
  cachedToken = data.access_token;
  return cachedToken!;
}

async function authedFetch(path: string, init: RequestInit = {}) {
  const token = await getToken();
  const headers = new Headers(init.headers);
  headers.set('Authorization', `Bearer ${token}`);
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  return fetch(`${API_BASE}${path}`, { ...init, headers });
}

export const api = {
  /** Get the full Home page bundle in a single request. */
  async getLanding() {
    const res = await authedFetch('/home/landing');
    if (!res.ok) throw new Error(`landing failed: ${res.status}`);
    return res.json();
  },
};
