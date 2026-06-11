/**
 * useAsk — runs a chat turn against /api/v1/chat/stream and returns
 * the aggregated AskTurn state. Re-renders incrementally as events stream in.
 */
import * as React from 'react';
import { chatStream } from './chatStream';
import { getToken } from './api';
import { useQueryClient } from '@tanstack/react-query';
import { redactForAnalytics, track } from './analytics';
import { randomUUID } from './uuid';
import type { AskTurn, ChatEvent } from '@/types/chat';

function emptyTurn(question: string, sessionId?: string | null): AskTurn {
  return {
    turnId: randomUUID(),
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
    startedAt: Date.now(),
    firstTokenMs: null,
    serverFirstTokenMs: null,
    totalMs: null,
    serverTotalMs: null,
    receivedAnswerDelta: false,
    followUps: [],
    error: null,
    streaming: true,
  };
}

function applyEvent(
  turn: AskTurn,
  e: ChatEvent,
  observed: { firstTokenMs?: number; elapsedMs?: number } = {}
): AskTurn {
  switch (e.type) {
    case 'stream_start':
      return { ...turn, sessionId: turn.sessionId ?? e.session_id ?? null };
    case 'first_token':
      return {
        ...turn,
        sessionId: turn.sessionId ?? e.session_id ?? null,
        firstTokenMs: turn.firstTokenMs ?? observed.firstTokenMs ?? e.time_ms,
        serverFirstTokenMs: e.time_ms,
      };
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
    case 'answer_delta':
      return {
        ...turn,
        sessionId: turn.sessionId ?? e.session_id ?? null,
        answer: `${turn.answer ?? ''}${e.delta}`,
        firstTokenMs: turn.firstTokenMs ?? observed.firstTokenMs ?? null,
        receivedAnswerDelta: true,
      };
    case 'answer':
      return {
        ...turn,
        sessionId: turn.sessionId ?? e.session_id ?? null,
        answer: e.content,
        firstTokenMs: turn.firstTokenMs ?? observed.firstTokenMs ?? null,
      };
    case 'stream_done':
      return {
        ...turn,
        sessionId: turn.sessionId ?? e.session_id ?? null,
        streaming: false,
        totalMs: observed.elapsedMs ?? turn.totalMs,
        serverTotalMs: e.duration_ms,
        serverFirstTokenMs: e.first_token_ms ?? turn.serverFirstTokenMs,
      };
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

      // Stream once with a token. If we get a 401 (typical: page open
      // longer than the 1h JWT TTL, so the cached token expired), bust
      // the cache and retry once with a fresh mint. Anything else
      // bubbles to the catch below.
      const streamOnce = async (token: string) => {
        let acc = initial;
        let firstTokenTracked = false;
        for await (const ev of chatStream({
          message,
          sessionId: opts.sessionId ?? undefined,
          token,
          signal: ctrl.signal,
        })) {
          const elapsedMs = Math.round(performance.now() - t0);
          const isFirstTokenEvent =
            ev.type === 'first_token' || ev.type === 'answer_delta' || ev.type === 'answer';
          const firstTokenMs =
            acc.firstTokenMs ?? (isFirstTokenEvent ? elapsedMs : undefined);

          acc = applyEvent(acc, ev, { firstTokenMs, elapsedMs });
          setTurn(acc);
          setLastUpdate(Date.now());

          if (!firstTokenTracked && acc.firstTokenMs !== null) {
            firstTokenTracked = true;
            track('answer.first_token', {
              ttft_ms: acc.firstTokenMs,
              server_ttft_ms: acc.serverFirstTokenMs,
              source: ev.type === 'first_token' ? ev.source ?? null : ev.type,
              is_continuation: Boolean(opts.sessionId),
            });
          }
        }
        return acc;
      };

      try {
        let acc: AskTurn;
        try {
          acc = await streamOnce(await getToken());
        } catch (err) {
          if (
            (err as Error).message?.includes('401') &&
            (err as Error).name !== 'AbortError'
          ) {
            // Reset turn so the streamed-but-rejected acc doesn't show
            // partial state, then retry with a freshly-minted token.
            setTurn(initial);
            acc = await streamOnce(await getToken(true));
          } else {
            throw err;
          }
        }
        // Finalize
        const durationMs = Math.round(performance.now() - t0);
        setTurn((prev) =>
          prev
            ? { ...prev, streaming: false, totalMs: prev.totalMs ?? durationMs }
            : prev
        );
        track('answer.received', {
          duration_ms: durationMs,
          ttft_ms: acc.firstTokenMs,
          server_ttft_ms: acc.serverFirstTokenMs,
          server_duration_ms: acc.serverTotalMs,
          streamed: acc.receivedAnswerDelta,
          output_chars: acc.answer?.length ?? 0,
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
