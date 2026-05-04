/** Shared types between backend and frontend. Keep these in sync with /api/v1/home/landing. */

export type SourceStatus = 'fresh' | 'stale' | 'error' | 'not_connected';
export type SourceType = 'postgres' | 'qdrant' | 'neo4j' | 's3' | 'slack' | 'notion' | 'github';
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
