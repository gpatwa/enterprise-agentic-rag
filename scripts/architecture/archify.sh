#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="https://github.com/tt-a1i/archify.git"
REVISION="5769acefcc2ebd696a4f9ed3ac9cb6cca1d75c70"

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cache_root="${ARCHIFY_CACHE_DIR:-${repo_root}/.cache/archify}"
tool_root="${cache_root}/${REVISION}"

for command in git node npm; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "archify: ${command} is required" >&2
    exit 1
  fi
done

node_major="$(node -p 'Number(process.versions.node.split(".")[0])')"
if (( node_major < 18 )); then
  echo "archify: Node.js 18 or newer is required" >&2
  exit 1
fi

mkdir -p "${cache_root}"

if [[ ! -x "${tool_root}/archify/bin/archify.mjs" ]]; then
  staging="$(mktemp -d "${cache_root}/.install.XXXXXX")"
  cleanup() {
    if [[ -n "${staging:-}" && -d "${staging}" ]]; then
      rm -rf -- "${staging}"
    fi
  }
  trap cleanup EXIT

  git init --quiet "${staging}"
  git -C "${staging}" remote add origin "${REPOSITORY}"
  git -C "${staging}" fetch --quiet --depth 1 origin "${REVISION}"
  git -C "${staging}" checkout --quiet --detach FETCH_HEAD

  resolved_revision="$(git -C "${staging}" rev-parse HEAD)"
  if [[ "${resolved_revision}" != "${REVISION}" ]]; then
    echo "archify: expected ${REVISION}, resolved ${resolved_revision}" >&2
    exit 1
  fi

  if [[ -e "${tool_root}" ]]; then
    echo "archify: incomplete cache exists at ${tool_root}; remove that cache entry and retry" >&2
    exit 1
  fi
  mv "${staging}" "${tool_root}"
  staging=""
  trap - EXIT
fi

resolved_revision="$(git -C "${tool_root}" rev-parse HEAD)"
if [[ "${resolved_revision}" != "${REVISION}" ]]; then
  echo "archify: cached checkout is not the pinned revision ${REVISION}" >&2
  exit 1
fi

if command -v sha256sum >/dev/null 2>&1; then
  lock_hash="$(sha256sum "${tool_root}/archify/package-lock.json" | awk '{print $1}')"
else
  lock_hash="$(shasum -a 256 "${tool_root}/archify/package-lock.json" | awk '{print $1}')"
fi
install_stamp="${tool_root}/archify/node_modules/.archify-lock-${lock_hash}"
if [[ ! -f "${install_stamp}" ]]; then
  npm --prefix "${tool_root}/archify" ci --ignore-scripts --no-audit --no-fund
  touch "${install_stamp}"
fi

export ARCHIFY_UPDATE_CHECK_DISABLED=1
exec node "${tool_root}/archify/bin/archify.mjs" "$@"
