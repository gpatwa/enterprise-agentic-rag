"""``scripts/setup_provider_keys_azure.sh`` against fake ``az``, ``curl``, ``terraform`` and ``kubectl``.

The keys the platform cannot generate are collected once, proven against the provider, stored in Key Vault under the
names the API reads, and never put on a command line or kept when the provider rejects them.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SCRIPT = REPO / "scripts" / "setup_provider_keys_azure.sh"

AZ = r"""#!/usr/bin/env bash
echo "az $*" >> "$FAKE_DIR/calls.log"
case "$*" in
  "account show"*) exit 0 ;;
  "keyvault secret show"*)
    name="$(sed -E 's/.*--name ([^ ]+).*/\1/' <<<"$*")"
    [ -f "$FAKE_DIR/kv/$name" ] && cat "$FAKE_DIR/kv/$name" || exit 1 ;;
  "keyvault secret set"*)
    name="$(sed -E 's/.*--name ([^ ]+).*/\1/' <<<"$*")"
    value="$(cat)"
    [ -n "${FAKE_TRUNCATE:-}" ] && value="${value:0:3}"
    printf %s "$value" > "$FAKE_DIR/kv/$name"
    echo "set $name" >> "$FAKE_DIR/sets.log" ;;
esac
"""
CURL = r"""#!/usr/bin/env bash
echo "curl $*" >> "$FAKE_DIR/calls.log"
cat > /dev/null
printf %s "${FAKE_CURL_STATUS:-200}"
"""
TERRAFORM = r"""#!/usr/bin/env bash
case "$*" in *"output -raw key_vault_name"*) echo kv-test ;; esac
"""


def _run(tmp_path: Path, env_extra: dict[str, str] | None = None, preset: dict[str, str] | None = None):
    bin_dir, fake = tmp_path / "bin", tmp_path / "fake"
    (fake / "kv").mkdir(parents=True)
    bin_dir.mkdir()
    for name, body in (("az", AZ), ("curl", CURL), ("terraform", TERRAFORM)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    for secret, value in (preset or {}).items():
        (fake / "kv" / secret).write_text(value)
    env = {k: v for k, v in os.environ.items() if k not in {"GOOGLE_API_KEY", "OPENAI_API_KEY"}}
    env.update({"PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_DIR": str(fake), "SKIP_CLUSTER": "1"})
    env.update(env_extra or {})
    result = subprocess.run(
        ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, cwd=REPO, timeout=60, stdin=subprocess.DEVNULL
    )
    calls = (fake / "calls.log").read_text() if (fake / "calls.log").exists() else ""
    sets = (fake / "sets.log").read_text() if (fake / "sets.log").exists() else ""
    return result, calls, sets, fake


KEYS = {"GOOGLE_API_KEY": "gemini-secret-value-123", "OPENAI_API_KEY": "openai-secret-value-456"}


def test_keys_from_the_environment_are_checked_stored_and_read_back(tmp_path: Path) -> None:
    result, calls, sets, fake = _run(tmp_path, KEYS)
    assert result.returncode == 0, result.stderr
    assert sorted(sets.split()) == ["gemini-api-key", "openai-api-key", "set", "set"]
    assert (fake / "kv" / "gemini-api-key").read_text() == KEYS["GOOGLE_API_KEY"]
    assert (fake / "kv" / "openai-api-key").read_text() == KEYS["OPENAI_API_KEY"]
    assert "generativelanguage.googleapis.com" in calls and "api.openai.com" in calls


def test_no_key_value_is_ever_on_a_command_line_or_in_the_output(tmp_path: Path) -> None:
    result, calls, _, _ = _run(tmp_path, KEYS)
    for value in KEYS.values():
        assert value not in calls, "a key value reached a command line"
        assert value not in result.stdout + result.stderr


def test_a_rejected_key_is_not_stored(tmp_path: Path) -> None:
    result, _, sets, _ = _run(tmp_path, {**KEYS, "FAKE_CURL_STATUS": "401"})
    assert result.returncode != 0 and "rejected by the provider" in result.stderr
    assert sets == ""


def test_a_missing_key_without_a_terminal_stops_and_names_it(tmp_path: Path) -> None:
    result, _, sets, _ = _run(tmp_path, {"OPENAI_API_KEY": KEYS["OPENAI_API_KEY"]})
    assert result.returncode != 0 and "GOOGLE_API_KEY" in result.stderr
    assert sets == ""


def test_a_key_already_in_key_vault_is_used_and_not_rewritten(tmp_path: Path) -> None:
    preset = {"gemini-api-key": KEYS["GOOGLE_API_KEY"], "openai-api-key": KEYS["OPENAI_API_KEY"]}
    result, _, sets, _ = _run(tmp_path, preset=preset)
    assert result.returncode == 0, result.stderr
    assert sets == "", "a second run must not rewrite unchanged secrets"
    assert "already in Key Vault" in result.stdout


def test_a_truncated_key_vault_copy_fails_loudly(tmp_path: Path) -> None:
    result, _, _, _ = _run(tmp_path, {**KEYS, "FAKE_TRUNCATE": "1"})
    assert result.returncode != 0 and "expected" in result.stderr


def test_it_applies_the_keys_to_the_cluster_unless_told_not_to() -> None:
    text = SCRIPT.read_text()
    tail = text[text.index("SKIP_CLUSTER"):]
    assert "bootstrap_cluster_azure.sh" in tail and "rollout restart" in tail
    assert re.search(r'secret set .*--name "\$secret" --file /dev/stdin', text), "the value must be passed on stdin"
