#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
frontend_host="${TUSKOMETR_FRONTEND_HOST:-127.0.0.1}"
frontend_port="${TUSKOMETR_FRONTEND_PORT:-3003}"
mode="${1:-frontend}"

if [[ "$mode" != frontend && "$mode" != --full ]]; then
  echo "Usage: $0 [--full]" >&2
  exit 1
fi

if [[ ! -x "${repo_root}/node_modules/.bin/vite" ]]; then
  echo "Frontend dependencies are missing. Run: npm ci" >&2
  exit 1
fi

export VITE_DATA_ORIGIN=""
if [[ "$mode" == frontend ]]; then
  # Vite serves the UI and proxies published JSON; no Docker services are started.
  exec npm --prefix "${repo_root}" run dev:web -- \
    --host "${frontend_host}" --port "${frontend_port}" --strictPort
fi

export TUSKOMETR_DATA_ORIGIN=http://127.0.0.1:8000

children=()
compose=(
  docker compose
  --project-name tuskometr-dev
  --file "${repo_root}/docker-compose.yml"
)

stop_children() {
  trap - EXIT INT TERM
  if ((${#children[@]})); then
    kill "${children[@]}" 2>/dev/null || true
    wait "${children[@]}" 2>/dev/null || true
  fi
  "${compose[@]}" down --remove-orphans >/dev/null 2>&1 || true
}
trap stop_children EXIT
trap 'exit 143' INT TERM

"${compose[@]}" up --build --remove-orphans web publisher worker backup &
children+=("$!")

npm --prefix "${repo_root}" run dev:web -- \
  --host "${frontend_host}" \
  --port "${frontend_port}" \
  --strictPort &
children+=("$!")

wait -n "${children[@]}"
