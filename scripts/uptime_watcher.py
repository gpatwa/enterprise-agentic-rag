#!/usr/bin/env python3
"""
Self-hosted uptime watcher for Compass alpha.

Polls /health/readiness once per invocation. On transitions (up→down or
down→up) posts a Slack message via incoming webhook. On steady state,
silent.

Designed for cron — run every minute (or every 5 minutes — match
UptimeRobot's free-tier cadence). Persists last-known status to a
state file so transitions are detected across runs.

Env vars
--------
    COMPASS_URL          (required)  Base URL of the deploy, e.g.
                                     https://alpha.compass.example.com
    SLACK_WEBHOOK_URL    (required)  Incoming webhook for alerts.
    HEALTH_PATH          /health/readiness   Endpoint to poll.
    TIMEOUT_SECONDS      5            HTTP timeout for the probe.
    STATE_FILE           /tmp/compass-uptime-state   Where last-known
                                                      state is stored.
    ALERT_ON_BOOT        0           If 1, send a "watcher started"
                                     Slack ping when no state file
                                     exists yet.

Exit codes
----------
    0  — current state up, OR transition handled
    1  — current state down (so cron's mail-on-error gives you a second
         channel)
    2  — misconfiguration (env var missing, state-file unwritable)

Why not a long-running daemon? A single-shot script under cron has zero
state-keeping bugs (cron handles re-running) and recovers automatically
from machine reboots. The state file is the only durable touchpoint.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_HEALTH_PATH = "/health/readiness"
DEFAULT_STATE_FILE = "/tmp/compass-uptime-state"
DEFAULT_TIMEOUT = 5


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def _required(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        sys.stderr.write(f"[uptime-watcher] missing required env var {name}\n")
        sys.exit(2)
    return v


def _probe(url: str, timeout: float) -> tuple[bool, int, str]:
    """
    Hit the readiness endpoint. Returns (is_up, http_status, summary).

    is_up is True iff HTTP 200; 503 (any-dep-down) counts as down.
    Network errors (DNS, refused, timeout) all count as down.
    """
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as res:
            body = res.read(4096).decode("utf-8", errors="replace")
            up = 200 <= res.status < 300
            return up, res.status, body[:300]
    except urllib.error.HTTPError as e:
        return False, e.code, str(e)[:300]
    except urllib.error.URLError as e:
        return False, 0, f"URL error: {e.reason}"
    except TimeoutError:
        return False, 0, "timeout"
    except Exception as e:  # pragma: no cover — defensive
        return False, 0, f"unexpected: {e!r}"[:300]


def _read_last_state(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except FileNotFoundError:
        return None
    except OSError as e:
        sys.stderr.write(f"[uptime-watcher] state read failed: {e}\n")
        return None


def _write_state(path: Path, state: str) -> None:
    try:
        path.write_text(state + "\n", encoding="utf-8")
    except OSError as e:
        sys.stderr.write(f"[uptime-watcher] state write failed: {e}\n")
        sys.exit(2)


def _post_slack(webhook: str, text: str, blocks: list[dict] | None = None) -> bool:
    """Best-effort Slack post. Returns True on 2xx."""
    payload: dict = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            return 200 <= res.status < 300
    except Exception as e:
        sys.stderr.write(f"[uptime-watcher] slack post failed: {e}\n")
        return False


def _build_alert(transition: str, base_url: str, status: int, detail: str) -> dict:
    if transition == "up":
        emoji, color, header = "✅", "good", "Compass alpha — back UP"
    else:
        emoji, color, header = "🔴", "danger", "Compass alpha — DOWN"
    text = f"{emoji} {header} ({status})"
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{emoji} {header}"},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*URL*\n{base_url}"},
                {"type": "mrkdwn", "text": f"*HTTP*\n`{status}`"},
            ],
        },
    ]
    if detail:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"_{detail[:200]}_"}],
            }
        )
    _ = color  # reserved for future Slack attachment color usage
    return {"text": text, "blocks": blocks}


def main() -> int:
    base_url = _required("COMPASS_URL").rstrip("/")
    webhook = _required("SLACK_WEBHOOK_URL")
    health_path = _env("HEALTH_PATH", DEFAULT_HEALTH_PATH) or DEFAULT_HEALTH_PATH
    timeout = float(_env("TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT)) or DEFAULT_TIMEOUT)
    state_file = Path(_env("STATE_FILE", DEFAULT_STATE_FILE) or DEFAULT_STATE_FILE)
    alert_on_boot = (_env("ALERT_ON_BOOT", "0") or "0") == "1"

    full_url = base_url + health_path
    is_up, http_status, detail = _probe(full_url, timeout)
    current = "up" if is_up else "down"
    last = _read_last_state(state_file)

    if last is None:
        # First run on this host — record state, optionally announce.
        _write_state(state_file, current)
        if alert_on_boot:
            payload = _build_alert(current, base_url, http_status, detail)
            payload["text"] = "🚦 Compass alpha uptime watcher starting"
            _post_slack(webhook, payload["text"], payload["blocks"])
        return 0 if is_up else 1

    if current != last:
        # Transition — post and update state.
        payload = _build_alert(current, base_url, http_status, detail)
        _post_slack(webhook, payload["text"], payload["blocks"])
        _write_state(state_file, current)

    return 0 if is_up else 1


if __name__ == "__main__":
    sys.exit(main())
