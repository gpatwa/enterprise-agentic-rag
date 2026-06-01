/** Shared types between backend and frontend. Keep these in sync with /api/v1/home/landing. */

export type SourceStatus = 'fresh' | 'stale' | 'error' | 'not_connected';
export type SourceType =
  | 'postgres'
  | 'qdrant'
  | 'neo4j'
  | 's3'
  | 'slack'
  | 'notion'
  | 'github'
  | 'zendesk'
  | 'intercom';
export type Scope = 'auto' | 'data' | 'docs' | 'code' | 'web';

export interface User {
  id: string;
  name: string;
  role: string;
  email?: string;
}

export interface Tenant {
  id: string;
  name: string;
  residency?: string;
}

export interface PinnedQuestion {
  id: string;
  title: string;
  last_run_at?: string;
  last_result_preview?: string;
}

export interface Thread {
  id: string;
  title: string;
  updated_at: string;
  message_count: number;
  active?: boolean;
  pinned?: boolean;
}

export interface ThreadMessage {
  id: number;
  role: 'user' | 'assistant' | string;
  content: string;
  created_at: string;
  metadata?: Record<string, unknown>;
}

export interface Annotation {
  id: number;
  tenant_id: string;
  annotation_type: string;
  key: string;
  value: string;
  created_by?: string;
  created_at: string;
  updated_at?: string;
}

export interface BusinessRule {
  id: number;
  tenant_id: string;
  context_type: string;
  key: string;
  value: string;
  applies_to_roles?: string[];
  priority?: number;
  created_at: string;
}

export interface CodeContextEntry {
  id: number;
  tenant_id: string;
  context_type: string;
  name: string;
  description: string;
  source_code?: string;
  created_at: string;
}

export interface SavedQuestionDetail {
  id: string;
  title: string;
  question_text: string;
  scope: string;
  pinned: boolean;
  last_run_at: string | null;
  last_result_preview: string | null;
}

export interface QuickStartCategory {
  id: string;
  icon: string;
  title: string;
  description: string;
  questions: { id: string; text: string }[];
}

export interface SourceHealth {
  type: SourceType;
  name: string;
  row_count?: number;
  chunk_count?: number;
  node_count?: number;
  ticket_count?: number;
  last_synced_at?: string;
  status: SourceStatus;
}

export interface KnowledgeCounts {
  glossary: number;
  business_rules: number;
  code_context: number;
}

export interface Governance {
  pii_redaction: boolean;
  audit_logging: boolean;
}

export interface LandingResponse {
  user: User;
  tenant: Tenant;
  pinned_questions: PinnedQuestion[];
  recent_threads: Thread[];
  quick_start_categories: QuickStartCategory[];
  sources: SourceHealth[];
  knowledge_counts: KnowledgeCounts;
  governance: Governance;
}

// ── MCP (Model Context Protocol) connectors ──────────────────────────

export type MCPConnectionStatus =
  | 'pending'
  | 'enabled'
  | 'disabled'
  | 'error';

export interface MCPCatalogEntry {
  server_name: string;
  display_name: string;
  description: string;
  required_credentials: string[];
  oauth_flow: 'oauth2' | null;
  docs_url: string | null;
}

export interface MCPCatalogResponse {
  catalog: MCPCatalogEntry[];
  mcp_enabled: boolean;
}

export interface MCPConnection {
  server_name: string;
  status: MCPConnectionStatus;
  last_health_check: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface MCPConnectionsResponse {
  connections: MCPConnection[];
  mcp_enabled: boolean;
}

export interface MCPTestResponse {
  ok: boolean;
  error_message: string | null;
}

export interface MCPToolDescriptor {
  server_name: string;
  tool_name: string;
  qualified_name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

// ── Support integrations ──────────────────────────────────────────────

export type SupportAuthMode = 'nango' | 'direct_env';
export type SupportConnectionStatus = 'pending' | 'connected' | 'error' | 'disabled';

export interface SupportCatalogEntry {
  provider: 'zendesk' | 'intercom';
  display_name: string;
  description: string;
  category: string;
  auth_modes: SupportAuthMode[];
  nango_provider_config_key: string;
  direct_env_vars: string[];
  objects: string[];
  docs_url: string | null;
}

export interface SupportCatalogResponse {
  catalog: SupportCatalogEntry[];
  support_integrations_enabled: boolean;
}

export interface SupportConnection {
  provider: 'zendesk' | 'intercom';
  auth_mode: SupportAuthMode;
  status: SupportConnectionStatus;
  nango_connection_id: string | null;
  provider_config_key: string | null;
  external_account_id: string | null;
  metadata: Record<string, unknown>;
  last_health_check: string | null;
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface SupportConnectionsResponse {
  connections: SupportConnection[];
  support_integrations_enabled: boolean;
}

export interface SupportTicketPreview {
  id: string;
  subject: string;
  status: string | null;
  requester: string | null;
  updated_at: string | null;
  url: string | null;
}

export interface SupportTicket {
  id: number;
  provider: string;
  external_id: string;
  subject: string;
  description: string | null;
  status: string | null;
  priority: string | null;
  category: string | null;
  channel: string | null;
  requester_external_id: string | null;
  assignee_external_id: string | null;
  organization_external_id: string | null;
  tags: string[];
  source_url: string | null;
  created_at_external: string | null;
  updated_at_external: string | null;
  last_synced_at: string;
}

export interface SupportTicketsResponse {
  tickets: SupportTicket[];
  total: number;
  limit: number;
  offset: number;
}

export interface SupportIndexSummary {
  tenant_id: string;
  provider: string | null;
  tickets_seen: number;
  tickets_total: number;
  comments_seen: number;
  comments_total: number;
  articles_seen: number;
  articles_total: number;
  indexed: number;
  skipped: number;
  chunks: number;
  errors: Array<{
    provider: string;
    source_type: string;
    source_id: string;
    error: string;
  }>;
}

export interface SupportSearchResult {
  id: string;
  score: number | null;
  provider: string | null;
  source_type: string | null;
  source_id: string | null;
  title: string | null;
  text: string;
  status: string | null;
  priority: string | null;
  tags: string[];
  source_url: string | null;
  chunk_index: number | null;
  chunk_count: number | null;
}

export interface SupportSearchResponse {
  results: SupportSearchResult[];
  query: string;
  limit: number;
}

export interface SupportCitation {
  label: string;
  provider: string | null;
  source_type: string | null;
  source_id: string | null;
  title: string | null;
  source_url: string | null;
  score: number | null;
}

export interface SupportResolution {
  answer: string;
  confidence: 'low' | 'medium' | 'high' | string;
  citations: SupportCitation[];
  matches: SupportSearchResult[];
  next_action: string;
}

export interface SupportResolveResponse {
  resolution: SupportResolution;
}

export interface SupportDemoSeedSummary {
  provider: string;
  sync_run_id: number;
  customers_created: number;
  tickets_seen: number;
  tickets_created: number;
  comments_seen: number;
  comments_created: number;
  articles_seen: number;
  articles_created: number;
}

export interface SupportSeedDemoResponse {
  seed: SupportDemoSeedSummary;
  index_status: 'succeeded' | 'failed' | string;
  index: SupportIndexSummary | null;
  index_error: string | null;
}

export interface SupportJob {
  id: string;
  tenant_id: string;
  requested_by: string;
  job_type: string;
  providers: string[];
  limit: number;
  seed_demo: boolean;
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'canceled' | string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  current_step: string | null;
  result: Record<string, unknown> | null;
  error_message: string | null;
  attempt_count: number;
  max_attempts: number;
  cancel_requested: boolean;
  canceled_at: string | null;
  retry_of_job_id: string | null;
  locked_by: string | null;
  locked_at: string | null;
  next_run_at: string | null;
}

export interface SupportJobSummary {
  counts: Record<string, number>;
  active_count: number;
  terminal_count: number;
  dead_letter_count: number;
  stale_running_count: number;
}

export interface SupportJobsResponse {
  jobs: SupportJob[];
}

export interface SupportJobResponse {
  job: SupportJob;
}

export interface SupportJobSummaryResponse {
  summary: SupportJobSummary;
}

// ── Feedback widget ───────────────────────────────────────────────────

export type FeedbackCategory = 'bug' | 'idea' | 'comment';

export interface FeedbackRequest {
  message: string;
  category: FeedbackCategory;
  current_url?: string;
  user_agent?: string;
}

export interface FeedbackResponse {
  ok: boolean;
  relayed_to_slack: boolean;
}
