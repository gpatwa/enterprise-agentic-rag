/** NDJSON event types emitted by /api/v1/chat/stream. */

export type PipelineNode =
  | 'planner'
  | 'retriever'
  | 'responder'
  | 'tool_node'
  | 'evaluator'
  | 'retry'
  | 'step_advance'
  | 'context_enricher'
  | 'data_analytics'
  | '__end__';

export interface StatusEvent {
  type: 'status';
  node: PipelineNode | string;
  session_id?: string;
  info?: string;
}

export interface ToolResultEvent {
  type: 'tool_result';
  tool_name: string;
  content: string;
  session_id?: string;
}

export interface EvaluationEvent {
  type: 'evaluation';
  score: number;
  reasoning?: string;
  session_id?: string;
}

export interface StepProgressEvent {
  type: 'step_progress';
  current_step: number;
  session_id?: string;
}

export interface StreamStartEvent {
  type: 'stream_start';
  session_id?: string;
}

export interface FirstTokenEvent {
  type: 'first_token';
  time_ms: number;
  source?: 'cache' | 'llm' | 'llm_stream' | string;
  session_id?: string;
}

export interface ContextImage {
  url: string;
  caption?: string;
  filename?: string;
}

export interface ContextImagesEvent {
  type: 'context_images';
  images: ContextImage[];
  session_id?: string;
}

export interface ContextLayersEvent {
  type: 'context_layers';
  content: string;
  session_id?: string;
}

export interface SqlQueryEvent {
  type: 'sql_query';
  sql: string;
  time_ms?: number;
  session_id?: string;
}

export interface DataResultEvent {
  type: 'data_result';
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  table_html?: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  chart_spec?: any;
  session_id?: string;
}

export interface DataErrorEvent {
  type: 'data_error';
  content: string;
  session_id?: string;
}

export interface AnswerEvent {
  type: 'answer';
  content: string;
  session_id?: string;
}

export interface AnswerDeltaEvent {
  type: 'answer_delta';
  delta: string;
  session_id?: string;
}

export interface StreamDoneEvent {
  type: 'stream_done';
  duration_ms: number;
  first_token_ms?: number | null;
  output_chars?: number;
  cached?: boolean;
  session_id?: string;
}

export interface ErrorEvent {
  type: 'error';
  content: string;
}

export interface FollowUpsEvent {
  type: 'follow_ups';
  suggestions: string[];
  session_id?: string;
}

export type ChatEvent =
  | StatusEvent
  | ToolResultEvent
  | EvaluationEvent
  | StepProgressEvent
  | StreamStartEvent
  | FirstTokenEvent
  | ContextImagesEvent
  | ContextLayersEvent
  | SqlQueryEvent
  | DataResultEvent
  | DataErrorEvent
  | AnswerEvent
  | AnswerDeltaEvent
  | StreamDoneEvent
  | ErrorEvent
  | FollowUpsEvent;

/** Aggregated state of a single ask → answer turn. */
export interface AskTurn {
  /** stable client-side id for React keys */
  turnId: string;
  /** the user's question (for re-render in the thread) */
  question: string;
  /** session_id from backend (becomes the thread id) */
  sessionId: string | null;
  /** node names that ran, in order of completion */
  steps: { node: string; at: number }[];
  /** evaluator score 0-5 */
  evalScore: number | null;
  evalReason: string | null;
  /** retrieved images (multimodal) */
  images: ContextImage[];
  /** business-context layers text injected into the prompt */
  contextLayers: string | null;
  /** generated SQL + execution time (data analytics) */
  sql: { sql: string; timeMs: number } | null;
  /** data analytics result table + chart */
  dataResult: DataResultEvent | null;
  /** data analytics error (if SQL failed) */
  dataError: string | null;
  /** other tool outputs (calculator, web search, etc.) */
  toolResults: { tool: string; content: string }[];
  /** final synthesized answer */
  answer: string | null;
  /** epoch ms when this turn started on the client */
  startedAt: number;
  /** client-observed time to first answer token/delta */
  firstTokenMs: number | null;
  /** server-measured time to first token when emitted by backend */
  serverFirstTokenMs: number | null;
  /** total client-observed stream duration */
  totalMs: number | null;
  /** total server-measured stream duration when emitted by backend */
  serverTotalMs: number | null;
  /** whether answer text streamed as deltas instead of only final answer */
  receivedAnswerDelta: boolean;
  /** suggested follow-up questions emitted at end of stream */
  followUps: string[];
  /** terminal error from the stream */
  error: string | null;
  /** whether the stream is still active */
  streaming: boolean;
}
