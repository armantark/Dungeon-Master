#!/usr/bin/env bash
# Starts the FastAPI backend and the Vite frontend for local development.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

# Prefer Apple Silicon Homebrew directly in task-launched shells, which may
# otherwise pick an older `/usr/local/bin/node` and `/usr/local/bin/brew`
# before the current brew-managed toolchain.
if [[ -d /opt/homebrew/bin ]]; then
  export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"
elif command -v brew >/dev/null 2>&1; then
  BREW_PREFIX="$(brew --prefix)"
  export PATH="$BREW_PREFIX/bin:$BREW_PREFIX/sbin:$PATH"
fi

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if ! command -v uv >/dev/null 2>&1; then
  echo "error: uv is not on PATH (https://github.com/astral-sh/uv)" >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "error: npm is not on PATH" >&2
  exit 1
fi

if ! command -v node >/dev/null 2>&1; then
  echo "error: node is not on PATH" >&2
  exit 1
fi

if ! node -e 'const [major, minor] = process.versions.node.split(".").map(Number); const ok = (major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major >= 23; process.exit(ok ? 0 : 1)'; then
  echo "error: Node.js $(node -v) is too old for this frontend. Please use Node 20.19+, 22.12+, or newer." >&2
  exit 1
fi

echo "Starting backend (127.0.0.1:8000)…"
uv run dungeon-master --reload &
BACKEND_PID=$!

if [[ ! -d web/node_modules ]]; then
  echo "Installing web dependencies…"
  (cd web && npm install)
fi

echo "Starting frontend (vite)…"
cd web
npm run dev
