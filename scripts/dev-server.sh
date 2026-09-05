#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
frontend_host="${TUSKOMETR_FRONTEND_HOST:-127.0.0.1}"
frontend_port="${TUSKOMETR_FRONTEND_PORT:-3003}"

if [[ ! -x "${repo_root}/frontend/node_modules/.bin/vite" ]]; then
  echo "Brak zależności frontendu. Uruchom: npm --prefix frontend install" >&2
  exit 1
fi

children=()
compose=(
  docker compose
  --project-name tuskometr-dev
  --file "${repo_root}/docker-compose.yml"
  --file "${repo_root}/docker-compose.dev.yml"
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

"${compose[@]}" up --build --remove-orphans web worker backup &
children+=("$!")

npm --prefix "${repo_root}/frontend" run dev -- \
  --host "${frontend_host}" \
  --port "${frontend_port}" \
  --strictPort &
children+=("$!")

wait -n "${children[@]}"
