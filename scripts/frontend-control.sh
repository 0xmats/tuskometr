#!/usr/bin/env bash
set -Eeuo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
unit=tuskometr-dev.service
case "${1:-}" in
  start)
    systemctl --user link "$repo_root/deploy/systemd/$unit"
    systemctl --user daemon-reload
    systemctl --user start "$unit"
    ;;
  stop)
    systemctl --user stop "$unit"
    ;;
  status)
    systemctl --user status "$unit" --no-pager
    ;;
  *)
    echo "Usage: $0 start|stop|status" >&2
    exit 1
    ;;
esac
