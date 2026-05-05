# services/api/app/mcp/process_pool.py
"""
Lazy-spawn / idle-reap pool of MCP subprocesses, keyed on (tenant_id, server_name).

Design summary
--------------
The MCP Python SDK exposes a session as an async-context-manager pair
(`stdio_client(...)` → `ClientSession(...)`). To reuse one session across
many tool calls without a re-spawn each time, we hold both contexts open
inside an `AsyncExitStack` and keep the entered objects in a dict.

Concurrency
-----------
Two correctness rules:

1. **Spawn-once-per-key.** Concurrent first-callers for the same
   (tenant, server) must not produce two subprocesses. Solved with a
   per-key `asyncio.Lock` and a re-check after acquiring it.
2. **Capacity check is process-global.** A single pod can host many
   tenants; we hard-cap simultaneous live entries via a process-wide lock
   guarding both the capacity test and the lock-dict mutation.

The pool itself is single-process. In a multi-pod deployment each pod
gets its own pool; that's fine — MCP servers are stateless over the
session boundary, and worst-case is a slightly higher cold-start rate.

Failure modes
-------------
- npx / node missing  → `MCPServerSpawnError("node-not-installed")`
- subprocess exits early or returns non-zero before initialize → `MCPServerSpawnError`
- subprocess hangs past `MCP_TOOL_TIMEOUT_SECONDS`  → `MCPToolTimeoutError`
- subprocess crashes mid-call  → exception propagates to caller AND the
  entry is evicted so the next caller respawns cleanly.

Anything else is upstream (credentials wrong → server returns auth error →
that's an MCPToolCallError, not a spawn issue).
"""
from __future__ import annotations

import asyncio
import logging
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Optional

from app.mcp.errors import (
    MCPCapacityError,
    MCPServerSpawnError,
    MCPToolTimeoutError,
)

logger = logging.getLogger(__name__)


# ── Soft-import MCP SDK ──────────────────────────────────────────────────
# We want the package importable even on machines without the SDK (CI
# unit tests mock the pool out). Import errors are deferred to spawn time
# so a missing dep surfaces as a clean spawn failure with a fix-it message.
try:
    from mcp.client.stdio import stdio_client

    from mcp import ClientSession, StdioServerParameters

    _SDK_IMPORT_ERROR: Optional[Exception] = None
except Exception as e:  # pragma: no cover — exercised via _SDK_IMPORT_ERROR test
    ClientSession = None  # type: ignore[assignment]
    StdioServerParameters = None  # type: ignore[assignment]
    stdio_client = None  # type: ignore[assignment]
    _SDK_IMPORT_ERROR = e


@dataclass
class _PoolEntry:
    """One live (tenant, server) subprocess + its session handle."""

    tenant_id: str
    server_name: str
    session: object  # ClientSession when SDK present, opaque otherwise
    exit_stack: AsyncExitStack
    last_used: float = field(default_factory=time.monotonic)
    in_flight: int = 0  # active tool calls; reaper avoids killing busy entries

    @property
    def key(self) -> tuple[str, str]:
        return (self.tenant_id, self.server_name)


class MCPProcessPool:
    """
    Single-process pool of live MCP sessions.

    Construct once during lifespan, call `start()` to launch the reaper,
    and `stop()` on shutdown. Tests use the same shape with the reaper
    disabled (idle_seconds=None).
    """

    def __init__(
        self,
        *,
        max_processes: int = 200,
        idle_seconds: Optional[int] = 600,
        tool_timeout_seconds: int = 30,
        # Test seam: lets tests inject a fake stdio_client + ClientSession
        # so they don't actually spawn npx subprocesses.
        _stdio_client_factory=None,
        _client_session_factory=None,
    ) -> None:
        self._max_processes = max_processes
        self._idle_seconds = idle_seconds
        self._tool_timeout = tool_timeout_seconds
        self._entries: dict[tuple[str, str], _PoolEntry] = {}
        self._spawn_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()
        self._reaper_task: Optional[asyncio.Task] = None
        # Real factories or test injections. Resolved at first use to keep
        # construction cheap and to honour SDK lazy-import.
        self._stdio_client_factory = _stdio_client_factory
        self._client_session_factory = _client_session_factory

    # ── Lifecycle ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Begin the idle-reaper loop. No-op if disabled or already started."""
        if self._idle_seconds is None or self._reaper_task is not None:
            return
        self._reaper_task = asyncio.create_task(
            self._reaper_loop(), name="mcp-pool-reaper"
        )

    async def stop(self) -> None:
        """Cancel reaper, close every live entry. Safe to call repeatedly."""
        if self._reaper_task is not None:
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reaper_task = None
        # Snapshot keys; close mutates the dict.
        for key in list(self._entries.keys()):
            await self._evict(key, reason="shutdown")

    # ── Public API ───────────────────────────────────────────────────────

    async def get_session(
        self,
        tenant_id: str,
        server_name: str,
        spawn_spec: "StdioServerParameters",  # type: ignore[name-defined]
    ):
        """
        Return a live ClientSession for (tenant, server), spawning if needed.

        Concurrent first-callers are serialised by a per-key lock; only one
        subprocess is launched. Subsequent calls hit the cache fast-path
        without any locking overhead.
        """
        key = (tenant_id, server_name)
        # Fast path
        entry = self._entries.get(key)
        if entry is not None:
            entry.last_used = time.monotonic()
            return entry.session

        # Slow path — serialise spawn
        spawn_lock = await self._get_spawn_lock(key)
        async with spawn_lock:
            # Re-check after acquiring lock: another waiter may have spawned.
            entry = self._entries.get(key)
            if entry is not None:
                entry.last_used = time.monotonic()
                return entry.session
            # Capacity gate
            async with self._global_lock:
                if (
                    self._max_processes
                    and len(self._entries) >= self._max_processes
                ):
                    raise MCPCapacityError(
                        "MCP process pool at capacity",
                        extra={
                            "max_processes": self._max_processes,
                            "live": len(self._entries),
                        },
                    )
            entry = await self._spawn(tenant_id, server_name, spawn_spec)
            self._entries[key] = entry
            logger.info(
                "mcp pool spawn ok tenant=%s server=%s live=%d",
                tenant_id, server_name, len(self._entries),
            )
            return entry.session

    async def evict(self, tenant_id: str, server_name: str) -> bool:
        """
        Tear down a specific entry (e.g., after a crashed call or admin disable).

        Returns True if an entry existed.
        """
        return await self._evict((tenant_id, server_name), reason="evicted")

    def stats(self) -> dict[str, int]:
        """Snapshot for observability/tests. No locking — best-effort."""
        return {
            "live": len(self._entries),
            "max": self._max_processes,
        }

    async def with_call(self, entry_key: tuple[str, str]):
        """
        Internal: context manager bumping the in_flight counter on an entry.

        Used by the manager's call_tool to guard against the reaper killing
        an entry mid-call. We expose it here (not just in manager) so the
        pool stays self-consistent.
        """
        entry = self._entries.get(entry_key)
        if entry is None:
            return _NullCallGuard()
        return _CallGuard(entry)

    # ── Internals ────────────────────────────────────────────────────────

    async def _get_spawn_lock(self, key: tuple[str, str]) -> asyncio.Lock:
        """Locks live in a dict; mutating the dict needs the global lock."""
        async with self._global_lock:
            lock = self._spawn_locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._spawn_locks[key] = lock
            return lock

    async def _spawn(
        self,
        tenant_id: str,
        server_name: str,
        spawn_spec: "StdioServerParameters",  # type: ignore[name-defined]
    ) -> _PoolEntry:
        """
        Open the stdio client + MCP session, retain both via AsyncExitStack.

        The exit stack is what makes "keep both contexts entered indefinitely"
        clean — no manual __aenter__/__aexit__ pairing.
        """
        if _SDK_IMPORT_ERROR is not None and self._stdio_client_factory is None:
            raise MCPServerSpawnError(
                "MCP SDK not installed: pip install 'mcp>=1.1.0'",
                extra={"import_error": str(_SDK_IMPORT_ERROR)},
            )

        stdio_factory = self._stdio_client_factory or stdio_client
        session_factory = self._client_session_factory or ClientSession

        stack = AsyncExitStack()
        try:
            transport = await stack.enter_async_context(stdio_factory(spawn_spec))
            # Real SDK: stdio_client yields (read, write) streams.
            # Tests can yield anything; session_factory accepts whatever.
            if isinstance(transport, tuple) and len(transport) == 2:
                read_stream, write_stream = transport
                session = await stack.enter_async_context(
                    session_factory(read_stream, write_stream)
                )
            else:
                session = await stack.enter_async_context(session_factory(transport))
            # MCP requires explicit initialize before tool calls.
            initialize = getattr(session, "initialize", None)
            if initialize is not None:
                await asyncio.wait_for(initialize(), timeout=self._tool_timeout)
        except asyncio.TimeoutError as e:
            await stack.aclose()
            raise MCPServerSpawnError(
                f"timeout initializing {server_name}",
                extra={"tenant_id": tenant_id, "server_name": server_name},
            ) from e
        except FileNotFoundError as e:
            # `npx` or `node` missing on the host — most common operator slip.
            await stack.aclose()
            raise MCPServerSpawnError(
                "node/npx not found on host — install Node.js to run MCP servers",
                extra={"tenant_id": tenant_id, "server_name": server_name},
            ) from e
        except Exception as e:
            await stack.aclose()
            raise MCPServerSpawnError(
                f"failed to spawn {server_name}: {e}",
                extra={"tenant_id": tenant_id, "server_name": server_name},
            ) from e

        return _PoolEntry(
            tenant_id=tenant_id,
            server_name=server_name,
            session=session,
            exit_stack=stack,
        )

    async def _evict(self, key: tuple[str, str], *, reason: str) -> bool:
        entry = self._entries.pop(key, None)
        if entry is None:
            return False
        try:
            await entry.exit_stack.aclose()
        except Exception as e:
            # Subprocess may already be dead. Log and move on.
            logger.warning(
                "mcp pool evict close failed key=%s reason=%s err=%s",
                key, reason, e,
            )
        logger.info(
            "mcp pool evict tenant=%s server=%s reason=%s live=%d",
            entry.tenant_id, entry.server_name, reason, len(self._entries),
        )
        return True

    async def _reaper_loop(self) -> None:
        """
        Wake every `idle_seconds / 5` (clamped 5–60s), reap idles, repeat.

        The reaper is best-effort: it skips entries with `in_flight > 0`
        even if their last_used is stale, because mid-call eviction would
        force the caller to handle a sudden EOF on the session.
        """
        assert self._idle_seconds is not None
        interval = max(5, min(60, self._idle_seconds // 5))
        try:
            while True:
                await asyncio.sleep(interval)
                cutoff = time.monotonic() - self._idle_seconds
                to_evict = [
                    k for k, e in self._entries.items()
                    if e.in_flight == 0 and e.last_used < cutoff
                ]
                for key in to_evict:
                    await self._evict(key, reason="idle")
        except asyncio.CancelledError:
            raise
        except Exception as e:  # pragma: no cover — paranoid catch
            logger.error("mcp reaper crashed: %s", e, exc_info=True)


# ── Call-guard helpers ───────────────────────────────────────────────────


class _CallGuard:
    """Bumps in_flight while a tool call is running; refreshes last_used on exit."""

    def __init__(self, entry: _PoolEntry) -> None:
        self._entry = entry

    async def __aenter__(self) -> _PoolEntry:
        self._entry.in_flight += 1
        return self._entry

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._entry.in_flight -= 1
        self._entry.last_used = time.monotonic()


class _NullCallGuard:
    """When the entry has been evicted between get_session() and call."""

    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


# Re-export the timeout class for callers (manager) without exposing SDK import.
__all__ = ["MCPProcessPool", "MCPToolTimeoutError"]
