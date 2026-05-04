/**
 * Thin API wrapper.
 * Dev: Vite proxies /api → http://localhost:8080.
 * Prod: same-origin requests after build is served by FastAPI.
 */

const API_BASE = '/api/v1';

let cachedToken: string | null = null;

export async function getToken(): Promise<string> {
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

interface ThreadsResponse {
  threads: import('@/types').Thread[];
}
interface SavedQuestionsResponse {
  saved_questions: import('@/types').SavedQuestionDetail[];
}

export const api = {
  /** Get the full Home page bundle in a single request. */
  async getLanding() {
    const res = await authedFetch('/home/landing');
    if (!res.ok) throw new Error(`landing failed: ${res.status}`);
    return res.json();
  },

  // ── Threads ─────────────────────────────────────────────────────
  async listThreads(opts: { limit?: number; pinnedOnly?: boolean } = {}): Promise<ThreadsResponse> {
    const params = new URLSearchParams();
    if (opts.limit) params.set('limit', String(opts.limit));
    if (opts.pinnedOnly) params.set('pinned_only', 'true');
    const res = await authedFetch(`/threads?${params}`);
    if (!res.ok) throw new Error(`listThreads failed: ${res.status}`);
    return res.json();
  },
  async pinThread(threadId: string, pinned: boolean) {
    const res = await authedFetch(`/threads/${threadId}/pin`, {
      method: 'POST',
      body: JSON.stringify({ pinned }),
    });
    if (!res.ok) throw new Error(`pinThread failed: ${res.status}`);
    return res.json();
  },
  async getThread(threadId: string) {
    const res = await authedFetch(`/threads/${threadId}`);
    if (!res.ok) throw new Error(`getThread failed: ${res.status}`);
    return res.json();
  },
  async getThreadMessages(threadId: string, limit = 50): Promise<{ thread_id: string; messages: import('@/types').ThreadMessage[] }> {
    const res = await authedFetch(`/threads/${threadId}/messages?limit=${limit}`);
    if (!res.ok) throw new Error(`getThreadMessages failed: ${res.status}`);
    return res.json();
  },

  // ── Sources ──────────────────────────────────────────────────────
  async getSourcesHealth(): Promise<{ sources: import('@/types').SourceHealth[]; probed_at: string }> {
    const res = await authedFetch('/sources/health');
    if (!res.ok) throw new Error(`getSourcesHealth failed: ${res.status}`);
    return res.json();
  },

  // ── Context layers (Knowledge admin) ─────────────────────────────
  async listAnnotations(annotationType?: string) {
    const q = annotationType ? `?annotation_type=${encodeURIComponent(annotationType)}` : '';
    const res = await authedFetch(`/context/annotations${q}`);
    if (!res.ok) throw new Error(`listAnnotations failed: ${res.status}`);
    return res.json();
  },
  async createAnnotation(body: { annotation_type: string; key: string; value: string; created_by?: string }) {
    const res = await authedFetch('/context/annotations', { method: 'POST', body: JSON.stringify(body) });
    if (!res.ok) throw new Error(`createAnnotation failed: ${res.status}`);
    return res.json();
  },
  async updateAnnotation(id: number, body: Partial<{ key: string; value: string }>) {
    const res = await authedFetch(`/context/annotations/${id}`, { method: 'PUT', body: JSON.stringify(body) });
    if (!res.ok) throw new Error(`updateAnnotation failed: ${res.status}`);
    return res.json();
  },
  async deleteAnnotation(id: number) {
    const res = await authedFetch(`/context/annotations/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`deleteAnnotation failed: ${res.status}`);
    return res.json();
  },

  async listBusinessRules() {
    const res = await authedFetch('/context/business-rules');
    if (!res.ok) throw new Error(`listBusinessRules failed: ${res.status}`);
    return res.json();
  },
  async createBusinessRule(body: { context_type: string; key: string; value: string; applies_to_roles?: string[]; priority?: number }) {
    const res = await authedFetch('/context/business-rules', { method: 'POST', body: JSON.stringify(body) });
    if (!res.ok) throw new Error(`createBusinessRule failed: ${res.status}`);
    return res.json();
  },
  async deleteBusinessRule(id: number) {
    const res = await authedFetch(`/context/business-rules/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`deleteBusinessRule failed: ${res.status}`);
    return res.json();
  },

  async listCodeContext() {
    const res = await authedFetch('/context/code-context');
    if (!res.ok) throw new Error(`listCodeContext failed: ${res.status}`);
    return res.json();
  },
  async createCodeContext(body: { context_type: string; name: string; description: string; source_code?: string }) {
    const res = await authedFetch('/context/code-context', { method: 'POST', body: JSON.stringify(body) });
    if (!res.ok) throw new Error(`createCodeContext failed: ${res.status}`);
    return res.json();
  },
  async deleteCodeContext(id: number) {
    const res = await authedFetch(`/context/code-context/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`deleteCodeContext failed: ${res.status}`);
    return res.json();
  },

  // ── Saved questions ──────────────────────────────────────────────
  async listSavedQuestions(opts: { limit?: number; pinnedOnly?: boolean } = {}): Promise<SavedQuestionsResponse> {
    const params = new URLSearchParams();
    if (opts.limit) params.set('limit', String(opts.limit));
    if (opts.pinnedOnly) params.set('pinned_only', 'true');
    const res = await authedFetch(`/saved-questions?${params}`);
    if (!res.ok) throw new Error(`listSavedQuestions failed: ${res.status}`);
    return res.json();
  },
  async createSavedQuestion(body: {
    title: string;
    question_text: string;
    scope?: string;
    pinned?: boolean;
  }) {
    const res = await authedFetch('/saved-questions', {
      method: 'POST',
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`createSavedQuestion failed: ${res.status}`);
    return res.json();
  },
  async updateSavedQuestion(
    id: string | number,
    patch: { title?: string; pinned?: boolean; last_result_preview?: string }
  ) {
    const res = await authedFetch(`/saved-questions/${id}`, {
      method: 'PUT',
      body: JSON.stringify(patch),
    });
    if (!res.ok) throw new Error(`updateSavedQuestion failed: ${res.status}`);
    return res.json();
  },
  async deleteSavedQuestion(id: string | number) {
    const res = await authedFetch(`/saved-questions/${id}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`deleteSavedQuestion failed: ${res.status}`);
    return res.json();
  },
};
