/**
 * TanStack Query hooks. All API access flows through these so caching,
 * retries, and refetch policy live in one place.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api';
import type {
  Annotation,
  BusinessRule,
  CodeContextEntry,
  LandingResponse,
  MCPCatalogResponse,
  MCPConnectionsResponse,
  MCPTestResponse,
  SavedQuestionDetail,
  SourceHealth,
  Thread,
  ThreadMessage,
} from '@/types';

export const queryKeys = {
  landing: ['home', 'landing'] as const,
  threads: (opts: { limit?: number; pinnedOnly?: boolean } = {}) =>
    ['threads', opts] as const,
  thread: (id: string) => ['threads', id] as const,
  savedQuestions: (opts: { pinnedOnly?: boolean } = {}) =>
    ['saved-questions', opts] as const,
  sourceHealth: ['sources', 'health'] as const,
  mcpCatalog: ['mcp', 'catalog'] as const,
  mcpConnections: ['mcp', 'connections'] as const,
};

export function useLanding() {
  return useQuery<LandingResponse>({
    queryKey: queryKeys.landing,
    queryFn: () => api.getLanding(),
    staleTime: 60_000,
  });
}

export function useThreads(opts: { limit?: number; pinnedOnly?: boolean } = {}) {
  return useQuery<{ threads: Thread[] }>({
    queryKey: queryKeys.threads(opts),
    queryFn: () => api.listThreads(opts),
    staleTime: 30_000,
  });
}

export function useThread(threadId: string | undefined) {
  return useQuery<Thread>({
    queryKey: ['threads', threadId],
    queryFn: () => api.getThread(threadId!),
    enabled: Boolean(threadId),
    staleTime: 30_000,
  });
}

export function useThreadMessages(threadId: string | undefined) {
  return useQuery<{ thread_id: string; messages: ThreadMessage[] }>({
    queryKey: ['threads', threadId, 'messages'],
    queryFn: () => api.getThreadMessages(threadId!),
    enabled: Boolean(threadId),
    staleTime: 15_000,
  });
}

export function usePinThread() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, pinned }: { id: string; pinned: boolean }) =>
      api.pinThread(id, pinned),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['threads'] });
      qc.invalidateQueries({ queryKey: queryKeys.landing });
    },
  });
}

export function useSavedQuestions(opts: { pinnedOnly?: boolean } = {}) {
  return useQuery<{ saved_questions: SavedQuestionDetail[] }>({
    queryKey: queryKeys.savedQuestions(opts),
    queryFn: () => api.listSavedQuestions(opts),
    staleTime: 30_000,
  });
}

export function useCreateSavedQuestion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      title: string;
      question_text: string;
      scope?: string;
      pinned?: boolean;
    }) => api.createSavedQuestion(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['saved-questions'] });
      qc.invalidateQueries({ queryKey: queryKeys.landing });
    },
  });
}

export function useUpdateSavedQuestion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      patch,
    }: {
      id: string | number;
      patch: { title?: string; pinned?: boolean; last_result_preview?: string };
    }) => api.updateSavedQuestion(id, patch),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['saved-questions'] });
      qc.invalidateQueries({ queryKey: queryKeys.landing });
    },
  });
}

export function useDeleteSavedQuestion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string | number) => api.deleteSavedQuestion(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['saved-questions'] });
      qc.invalidateQueries({ queryKey: queryKeys.landing });
    },
  });
}

// ── Sources health ──────────────────────────────────────────────────

export function useSourcesHealth() {
  return useQuery<{ sources: SourceHealth[]; probed_at: string }>({
    queryKey: queryKeys.sourceHealth,
    queryFn: () => api.getSourcesHealth(),
    // Probes are slow-ish — cache 60s, auto-refresh every 5min
    staleTime: 60_000,
    refetchInterval: 5 * 60_000,
  });
}

// ── Knowledge: glossary (annotations) ───────────────────────────────

export function useGlossary() {
  return useQuery<Annotation[]>({
    queryKey: ['context', 'annotations', 'glossary'],
    queryFn: () => api.listAnnotations('glossary'),
    staleTime: 30_000,
  });
}

export function useCreateGlossaryTerm() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { key: string; value: string }) =>
      api.createAnnotation({ ...body, annotation_type: 'glossary' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['context'] });
      qc.invalidateQueries({ queryKey: queryKeys.landing });
    },
  });
}

export function useDeleteAnnotation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteAnnotation(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['context'] });
      qc.invalidateQueries({ queryKey: queryKeys.landing });
    },
  });
}

// ── Knowledge: business rules ───────────────────────────────────────

export function useBusinessRules() {
  return useQuery<BusinessRule[]>({
    queryKey: ['context', 'business-rules'],
    queryFn: () => api.listBusinessRules(),
    staleTime: 30_000,
  });
}

export function useCreateBusinessRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      context_type: string;
      key: string;
      value: string;
      applies_to_roles?: string[];
      priority?: number;
    }) => api.createBusinessRule(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['context'] });
      qc.invalidateQueries({ queryKey: queryKeys.landing });
    },
  });
}

export function useDeleteBusinessRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteBusinessRule(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['context'] });
      qc.invalidateQueries({ queryKey: queryKeys.landing });
    },
  });
}

// ── Knowledge: code context ─────────────────────────────────────────

export function useCodeContext() {
  return useQuery<CodeContextEntry[]>({
    queryKey: ['context', 'code-context'],
    queryFn: () => api.listCodeContext(),
    staleTime: 30_000,
  });
}

export function useCreateCodeContext() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      context_type: string;
      name: string;
      description: string;
      source_code?: string;
    }) => api.createCodeContext(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['context'] });
      qc.invalidateQueries({ queryKey: queryKeys.landing });
    },
  });
}

export function useDeleteCodeContext() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteCodeContext(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['context'] });
      qc.invalidateQueries({ queryKey: queryKeys.landing });
    },
  });
}

// ── MCP connectors ──────────────────────────────────────────────────

export function useMcpCatalog() {
  return useQuery<MCPCatalogResponse>({
    queryKey: queryKeys.mcpCatalog,
    queryFn: () => api.getMcpCatalog(),
    // Static catalog — refresh sparingly
    staleTime: 5 * 60_000,
  });
}

export function useMcpConnections() {
  return useQuery<MCPConnectionsResponse>({
    queryKey: queryKeys.mcpConnections,
    queryFn: () => api.getMcpConnections(),
    staleTime: 30_000,
  });
}

export function useEnableMcp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { server_name: string; credentials: Record<string, string> }) =>
      api.enableMcp(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.mcpConnections });
    },
  });
}

export function useDisableMcp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (serverName: string) => api.disableMcp(serverName),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.mcpConnections });
    },
  });
}

export function useRemoveMcp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (serverName: string) => api.removeMcp(serverName),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.mcpConnections });
    },
  });
}

export function useTestMcp() {
  const qc = useQueryClient();
  return useMutation<MCPTestResponse, Error, string>({
    mutationFn: (serverName: string) => api.testMcp(serverName),
    onSuccess: () => {
      // status / last_health_check change — invalidate the connection list.
      qc.invalidateQueries({ queryKey: queryKeys.mcpConnections });
    },
  });
}
