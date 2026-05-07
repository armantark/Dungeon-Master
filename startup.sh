#!/usr/bin/env bash
# Starts the FastAPI backend and the Vite frontend for local development.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

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
