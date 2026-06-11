/**
 * Thin API wrapper.
 * Dev: Vite proxies /api → http://localhost:8080.
 * Prod: same-origin requests after build is served by FastAPI.
 */

const API_BASE = '/api/v1';

let cachedToken: string | null = null;

/**
 * Get a JWT for the current session. Caches in module scope.
 *
 * Pass `force=true` to bust the cache and re-mint — used by the
 * authedFetch retry path when a request comes back 401 (token expired).
 */
export async function getToken(force = false): Promise<string> {
  if (cachedToken && !force) return cachedToken;
  cachedToken = null;
  const res = await fetch('/auth/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: 'ui-user', role: 'admin' }),
  });
  if (!res.ok) {
    throw new Error(`Failed to mint token: ${res.status}`);
  }
  const data = await res.json();
  cachedToken = data.access_token;
  return cachedToken!;
}

/**
 * fetch wrapper that retries once on 401 with a fresh-minted token.
 * Handles the "JWT expired (1h TTL) — page has been open longer than that"
 * case without forcing the user to hard-reload.
 */
async function authedFetch(path: string, init: RequestInit = {}) {
  const doFetch = async (token: string) => {
    const headers = new Headers(init.headers);
    headers.set('Authorization', `Bearer ${token}`);
    if (init.body && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }
    return fetch(`${API_BASE}${path}`, { ...init, headers });
  };

  let res = await doFetch(await getToken());
  if (res.status === 401) {
    // Token rejected — bust cache, re-mint, retry exactly once.
    res = await doFetch(await getToken(true));
  }
  return res;
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

  // ── Support integrations ───────────────────────────────────────────
  async getSupportCatalog(): Promise<import('@/types').SupportCatalogResponse> {
    const res = await authedFetch('/support-integrations/catalog');
    if (!res.ok) throw new Error(`getSupportCatalog failed: ${res.status}`);
    return res.json();
  },
  async getSupportConnections(): Promise<import('@/types').SupportConnectionsResponse> {
    const res = await authedFetch('/support-integrations/connections');
    if (!res.ok) throw new Error(`getSupportConnections failed: ${res.status}`);
    return res.json();
  },
  async upsertSupportConnection(body: {
    provider: 'zendesk' | 'intercom';
    auth_mode: import('@/types').SupportAuthMode;
    nango_connection_id?: string | null;
    provider_config_key?: string | null;
    external_account_id?: string | null;
  }): Promise<{ connection: import('@/types').SupportConnection }> {
    const res = await authedFetch('/support-integrations/connections', {
      method: 'POST',
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`upsertSupportConnection failed: ${res.status}`);
    return res.json();
  },
  async testSupportConnection(provider: 'zendesk' | 'intercom') {
    const res = await authedFetch(`/support-integrations/connections/${provider}/test`, {
      method: 'POST',
    });
    if (!res.ok) throw new Error(`testSupportConnection failed: ${res.status}`);
    return res.json();
  },
  async removeSupportConnection(provider: 'zendesk' | 'intercom') {
    const res = await authedFetch(`/support-integrations/connections/${provider}`, {
      method: 'DELETE',
    });
    if (!res.ok) throw new Error(`removeSupportConnection failed: ${res.status}`);
    return res.json();
  },

  // ── Support Resolution Intelligence ────────────────────────────────
  async listSupportTickets(opts: {
    provider?: 'zendesk' | 'intercom';
    status?: string;
    limit?: number;
    offset?: number;
  } = {}): Promise<import('@/types').SupportTicketsResponse> {
    const params = new URLSearchParams();
    if (opts.provider) params.set('provider', opts.provider);
    if (opts.status) params.set('status', opts.status);
    if (opts.limit) params.set('limit', String(opts.limit));
    if (opts.offset) params.set('offset', String(opts.offset));
    const q = params.toString();
    const res = await authedFetch(`/support/tickets${q ? `?${q}` : ''}`);
    if (!res.ok) throw new Error(`listSupportTickets failed: ${res.status}`);
    return res.json();
  },
  async indexSupportTickets(opts: {
    provider?: 'zendesk' | 'intercom';
    limit?: number;
  } = {}): Promise<{ index: import('@/types').SupportIndexSummary }> {
    const params = new URLSearchParams();
    if (opts.provider) params.set('provider', opts.provider);
    if (opts.limit) params.set('limit', String(opts.limit));
    const q = params.toString();
    const res = await authedFetch(`/support/index${q ? `?${q}` : ''}`, {
      method: 'POST',
    });
    if (!res.ok) throw new Error(`indexSupportTickets failed: ${res.status}`);
    return res.json();
  },
  async searchSupportIndex(opts: {
    q: string;
    provider?: 'zendesk' | 'intercom';
    status?: string;
    limit?: number;
  }): Promise<import('@/types').SupportSearchResponse> {
    const params = new URLSearchParams({ q: opts.q });
    if (opts.provider) params.set('provider', opts.provider);
    if (opts.status) params.set('status', opts.status);
    if (opts.limit) params.set('limit', String(opts.limit));
    const res = await authedFetch(`/support/search?${params}`);
    if (!res.ok) throw new Error(`searchSupportIndex failed: ${res.status}`);
    return res.json();
  },
  async resolveSupportIssue(opts: {
    question: string;
    provider?: 'zendesk' | 'intercom';
    status?: string;
    limit?: number;
  }): Promise<import('@/types').SupportResolveResponse> {
    const res = await authedFetch('/support/resolve', {
      method: 'POST',
      body: JSON.stringify(opts),
    });
    if (!res.ok) throw new Error(`resolveSupportIssue failed: ${res.status}`);
    return res.json();
  },
  async seedSupportDemo(): Promise<import('@/types').SupportSeedDemoResponse> {
    const res = await authedFetch('/support/demo/seed', {
      method: 'POST',
    });
    if (!res.ok) throw new Error(`seedSupportDemo failed: ${res.status}`);
    return res.json();
  },
  async getSupportRepeatInsights(opts: {
    provider?: 'zendesk' | 'intercom';
    status?: string;
    limit?: number;
    min_count?: number;
  } = {}): Promise<import('@/types').SupportRepeatInsightsResponse> {
    const params = new URLSearchParams();
    if (opts.provider) params.set('provider', opts.provider);
    if (opts.status) params.set('status', opts.status);
    if (opts.limit) params.set('limit', String(opts.limit));
    if (opts.min_count) params.set('min_count', String(opts.min_count));
    const q = params.toString();
    const res = await authedFetch(`/support/insights/repeats${q ? `?${q}` : ''}`);
    if (!res.ok) throw new Error(`getSupportRepeatInsights failed: ${res.status}`);
    return res.json();
  },
  async buildSupportResolutionWorkflow(opts: {
    cluster_id?: string;
    provider?: 'zendesk' | 'intercom';
    status?: string;
    limit?: number;
    min_count?: number;
  }): Promise<import('@/types').SupportResolutionWorkflowResponse> {
    const res = await authedFetch('/support/insights/repeats/workflow', {
      method: 'POST',
      body: JSON.stringify(opts),
    });
    if (!res.ok) throw new Error(`buildSupportResolutionWorkflow failed: ${res.status}`);
    return res.json();
  },
  async startSupportSyncIndexJob(opts: {
    providers?: Array<'zendesk' | 'intercom'>;
    limit?: number;
    seed_demo?: boolean;
  } = {}): Promise<import('@/types').SupportJobResponse> {
    const res = await authedFetch('/support/jobs/sync-index', {
      method: 'POST',
      body: JSON.stringify(opts),
    });
    if (!res.ok) throw new Error(`startSupportSyncIndexJob failed: ${res.status}`);
    return res.json();
  },
  async listSupportJobs(limit = 20): Promise<import('@/types').SupportJobsResponse> {
    const res = await authedFetch(`/support/jobs?limit=${limit}`);
    if (!res.ok) throw new Error(`listSupportJobs failed: ${res.status}`);
    return res.json();
  },
  async getSupportJob(jobId: string): Promise<import('@/types').SupportJobResponse> {
    const res = await authedFetch(`/support/jobs/${encodeURIComponent(jobId)}`);
    if (!res.ok) throw new Error(`getSupportJob failed: ${res.status}`);
    return res.json();
  },
  async getSupportJobSummary(): Promise<import('@/types').SupportJobSummaryResponse> {
    const res = await authedFetch('/support/jobs/summary');
    if (!res.ok) throw new Error(`getSupportJobSummary failed: ${res.status}`);
    return res.json();
  },
  async cancelSupportJob(jobId: string): Promise<import('@/types').SupportJobResponse> {
    const res = await authedFetch(`/support/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: 'POST',
    });
    if (!res.ok) throw new Error(`cancelSupportJob failed: ${res.status}`);
    return res.json();
  },
  async retrySupportJob(jobId: string): Promise<import('@/types').SupportJobResponse> {
    const res = await authedFetch(`/support/jobs/${encodeURIComponent(jobId)}/retry`, {
      method: 'POST',
    });
    if (!res.ok) throw new Error(`retrySupportJob failed: ${res.status}`);
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

  // ── MCP connectors ───────────────────────────────────────────────
  async getMcpCatalog(): Promise<import('@/types').MCPCatalogResponse> {
    const res = await authedFetch('/mcp/catalog');
    if (!res.ok) throw new Error(`getMcpCatalog failed: ${res.status}`);
    return res.json();
  },
  async getMcpConnections(): Promise<import('@/types').MCPConnectionsResponse> {
    const res = await authedFetch('/mcp/connections');
    if (!res.ok) throw new Error(`getMcpConnections failed: ${res.status}`);
    return res.json();
  },
  async enableMcp(body: { server_name: string; credentials: Record<string, string> }) {
    const res = await authedFetch('/mcp/connections', {
      method: 'POST',
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      // Forward the structured detail body so the UI can surface a useful message.
      let detail: unknown;
      try {
        detail = await res.json();
      } catch {
        detail = null;
      }
      const err = new Error(`enableMcp failed: ${res.status}`) as Error & {
        status?: number;
        detail?: unknown;
      };
      err.status = res.status;
      err.detail = detail;
      throw err;
    }
    return res.json();
  },
  async disableMcp(serverName: string) {
    const res = await authedFetch(`/mcp/connections/${serverName}/disable`, {
      method: 'POST',
    });
    if (!res.ok) throw new Error(`disableMcp failed: ${res.status}`);
    return res.json();
  },
  async removeMcp(serverName: string) {
    const res = await authedFetch(`/mcp/connections/${serverName}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`removeMcp failed: ${res.status}`);
    return res.json();
  },
  async testMcp(serverName: string): Promise<import('@/types').MCPTestResponse> {
    const res = await authedFetch(`/mcp/connections/${serverName}/test`, {
      method: 'POST',
    });
    if (!res.ok) throw new Error(`testMcp failed: ${res.status}`);
    return res.json();
  },

  // ── Feedback widget ──────────────────────────────────────────────
  async submitFeedback(
    body: import('@/types').FeedbackRequest
  ): Promise<import('@/types').FeedbackResponse> {
    const res = await authedFetch('/feedback', {
      method: 'POST',
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      let detail: unknown;
      try {
        detail = await res.json();
      } catch {
        detail = null;
      }
      const err = new Error(`submitFeedback failed: ${res.status}`) as Error & {
        status?: number;
        detail?: unknown;
      };
      err.status = res.status;
      err.detail = detail;
      throw err;
    }
    return res.json();
  },
};
