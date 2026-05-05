/**
 * useAsk — runs a chat turn against /api/v1/chat/stream and returns
 * the aggregated AskTurn state. Re-renders incrementally as events stream in.
 */
import * as React from 'react';
import { chatStream } from './chatStream';
import { getToken } from './api';
import { useQueryClient } from '@tanstack/react-query';
import { redactForAnalytics, track } from './analytics';
import type { AskTurn, ChatEvent } from '@/types/chat';

function emptyTurn(question: string, sessionId?: string | null): AskTurn {
  return {
    turnId: crypto.randomUUID(),
    question,
    sessionId: sessionId ?? null,
    steps: [],
    evalScore: null,
    evalReason: null,
    images: [],
    contextLayers: null,
    sql: null,
    dataResult: null,
    dataError: null,
    toolResults: [],
    answer: null,
    followUps: [],
    error: null,
    streaming: true,
  };
}

function applyEvent(turn: AskTurn, e: ChatEvent): AskTurn {
  switch (e.type) {
    case 'status': {
      // Capture session_id on the first status event
      const sessionId = turn.sessionId ?? e.session_id ?? null;
      if (e.node === '__end__') {
        return { ...turn, sessionId, streaming: false };
      }
      // Avoid duplicate steps
      if (turn.steps.length > 0 && turn.steps[turn.steps.length - 1].node === e.node) {
        return { ...turn, sessionId };
      }
      return {
        ...turn,
        sessionId,
        steps: [...turn.steps, { node: e.node, at: Date.now() }],
      };
    }
    case 'tool_result':
      return {
        ...turn,
        toolResults: [...turn.toolResults, { tool: e.tool_name, content: e.content }],
      };
    case 'evaluation':
      return { ...turn, evalScore: e.score, evalReason: e.reasoning ?? null };
    case 'context_images':
      return { ...turn, images: e.images };
    case 'context_layers':
      return { ...turn, contextLayers: e.content };
    case 'sql_query':
      return { ...turn, sql: { sql: e.sql, timeMs: e.time_ms ?? 0 } };
    case 'data_result':
      return { ...turn, dataResult: e };
    case 'data_error':
      return { ...turn, dataError: e.content };
    case 'answer':
      return { ...turn, answer: e.content };
    case 'follow_ups':
      return { ...turn, followUps: e.suggestions };
    case 'error':
      return { ...turn, error: e.content, streaming: false };
    case 'step_progress':
      return turn;
    default:
      return turn;
  }
}

export function useAsk() {
  const [turn, setTurn] = React.useState<AskTurn | null>(null);
  const [lastUpdate, setLastUpdate] = React.useState<number>(Date.now());
  const abortRef = React.useRef<AbortController | null>(null);
  const qc = useQueryClient();

  const ask = React.useCallback(
    async (message: string, opts: { sessionId?: string | null } = {}) => {
      // Cancel any in-flight stream
      abortRef.current?.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;

      const initial = emptyTurn(message, opts.sessionId ?? null);
      setTurn(initial);
      setLastUpdate(Date.now());

      const t0 = performance.now();
      track('question.asked', {
        question_preview: redactForAnalytics(message),
        question_len: message.length,
        is_continuation: Boolean(opts.sessionId),
      });

      try {
        const token = await getToken();
        let acc = initial;
        for await (const ev of chatStream({
          message,
          sessionId: opts.sessionId ?? undefined,
          token,
          signal: ctrl.signal,
        })) {
          acc = applyEvent(acc, ev);
          setTurn(acc);
          setLastUpdate(Date.now());
        }
        // Finalize
        setTurn((prev) => (prev ? { ...prev, streaming: false } : prev));
        track('answer.received', {
          duration_ms: Math.round(performance.now() - t0),
          had_sql: Boolean(acc.sql),
          had_data: Boolean(acc.dataResult),
          eval_score: acc.evalScore ?? null,
          steps: acc.steps.length,
        });
        // Refresh anything that depends on chat state
        qc.invalidateQueries({ queryKey: ['threads'] });
        qc.invalidateQueries({ queryKey: ['home', 'landing'] });
      } catch (err) {
        if ((err as Error).name === 'AbortError') return;
        track('answer.errored', {
          duration_ms: Math.round(performance.now() - t0),
          error: (err as Error).message?.slice(0, 80),
        });
        setTurn((prev) =>
          prev
            ? { ...prev, error: (err as Error).message, streaming: false }
            : prev
        );
      }
    },
    [qc]
  );

  const reset = React.useCallback(() => {
    abortRef.current?.abort();
    setTurn(null);
  }, []);

  React.useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  return {
    turn,
    ask,
    reset,
    streaming: turn?.streaming ?? false,
    lastUpdate,
  };
}
