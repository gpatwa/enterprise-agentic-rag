/**
 * NDJSON streaming client for /api/v1/chat/stream.
 *
 * Returns an async generator of ChatEvent. Handles partial-line buffering,
 * decoder edge cases, and abort signals.
 */
import type { ChatEvent } from '@/types/chat';

const CHAT_ENDPOINT = '/api/v1/chat/stream';

interface StreamArgs {
  message: string;
  sessionId?: string | null;
  token: string;
  signal?: AbortSignal;
}

export async function* chatStream({
  message,
  sessionId,
  token,
  signal,
}: StreamArgs): AsyncGenerator<ChatEvent, void, void> {
  const res = await fetch(CHAT_ENDPOINT, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      message,
      ...(sessionId ? { session_id: sessionId } : {}),
    }),
    signal,
  });

  if (!res.ok || !res.body) {
    throw new Error(`chat stream failed: ${res.status} ${res.statusText}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // NDJSON: split on newline; keep last partial line in buffer
      let nl: number;
      while ((nl = buffer.indexOf('\n')) !== -1) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        if (!line) continue;
        try {
          yield JSON.parse(line) as ChatEvent;
        } catch {
          // Tolerate malformed lines; do not crash the whole stream.
          // eslint-disable-next-line no-console
          console.warn('Bad NDJSON line:', line);
        }
      }
    }
    // Flush any trailing line
    const tail = buffer.trim();
    if (tail) {
      try {
        yield JSON.parse(tail) as ChatEvent;
      } catch {
        // ignore
      }
    }
  } finally {
    reader.releaseLock();
  }
}
