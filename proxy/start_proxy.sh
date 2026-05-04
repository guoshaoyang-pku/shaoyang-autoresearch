#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="${ROOT}/proxy/proxy.launch.log"
PROXY_SCRIPT="${ROOT}/proxy/codex_proxy.py"

if [[ ! -f "$PROXY_SCRIPT" ]]; then
  echo "missing: $PROXY_SCRIPT" >&2
  exit 1
fi

PY="$(command -v python3)"
if [[ -x /opt/homebrew/Caskroom/miniconda/base/bin/python3 ]]; then
  PY=/opt/homebrew/Caskroom/miniconda/base/bin/python3
fi

pkill -f "python.*${PROXY_SCRIPT}" 2>/dev/null || true
sleep 0.4
nohup "$PY" "$PROXY_SCRIPT" >>"$LOG_FILE" 2>&1 </dev/null &
disown || true
sleep 0.4

PORT="${CODEX_PROXY_LISTEN_PORT:-4002}"
if curl -fsS "http://127.0.0.1:${PORT}/" >/dev/null; then
  echo "codex proxy up on http://127.0.0.1:${PORT} (log: $LOG_FILE)"
else
  echo "codex proxy failed health check; see $LOG_FILE" >&2
  exit 1
fi
