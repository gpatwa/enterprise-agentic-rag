/**
 * TanStack Query hooks. All API access flows through these so caching,
 * retries, and refetch policy live in one place.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './api';
import type { LandingResponse, SavedQuestionDetail, Thread } from '@/types';

export const queryKeys = {
  landing: ['home', 'landing'] as const,
  threads: (opts: { limit?: number; pinnedOnly?: boolean } = {}) =>
    ['threads', opts] as const,
  thread: (id: string) => ['threads', id] as const,
  savedQuestions: (opts: { pinnedOnly?: boolean } = {}) =>
    ['saved-questions', opts] as const,
  sourceHealth: ['sources', 'health'] as const,
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
