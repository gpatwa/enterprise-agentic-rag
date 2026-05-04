/**
 * TanStack Query hooks. All API access flows through these so caching,
 * retries, and refetch policy live in one place.
 */
import { useQuery } from '@tanstack/react-query';
import { api } from './api';
import type { LandingResponse } from '@/types';

export const queryKeys = {
  landing: ['home', 'landing'] as const,
  threads: (limit: number) => ['threads', { limit }] as const,
  thread: (id: string) => ['threads', id] as const,
  savedQuestions: ['saved-questions'] as const,
  sourceHealth: ['sources', 'health'] as const,
};

export function useLanding() {
  return useQuery<LandingResponse>({
    queryKey: queryKeys.landing,
    queryFn: () => api.getLanding(),
    // Stale after 60s; right rail's "freshness" badges use this signal.
    staleTime: 60_000,
  });
}
