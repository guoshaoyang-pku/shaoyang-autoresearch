#!/usr/bin/env bash
# tick.sh: launchd / cron 入口，对每个 worker 拉起一次 manager LLM (codex)。
#
# 用法：
#   ./tick.sh                # 跑所有 enabled worker
#   ./tick.sh paper_a        # 只跑指定 worker
#
# 流程：
#   1. 读 state/manager_chats.json 拿每个 worker 的 codex session_id
#   2. 委托 scripts/_invoke_manager.py tick → codex CLI（仅 codex 一个 backend）
#   3. 解析最后一行 JSON 写入 state/manager_audits/<worker>.jsonl
#   4. 失败则写 escalations.jsonl
#
# Backend 不再可配；cursor-agent 已彻底从 in-loop 中移除。

set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

WORKER_FILTER="${1:-}"
TS="$(date -Iseconds)"
AUDITS_DIR="$ROOT/state/manager_audits"
LOG_FILE="$ROOT/state/tick.log"
CHATS_FILE="$ROOT/state/manager_chats.json"
INVOKE="$ROOT/scripts/_invoke_manager.py"

mkdir -p "$AUDITS_DIR" "$ROOT/state"

if [[ ! -f "$CHATS_FILE" ]]; then
  echo "[$TS] manager session 信息不存在，先跑 ./kickoff.sh" | tee -a "$LOG_FILE"
  exit 1
fi

if [[ ! -f "$INVOKE" ]]; then
  echo "[$TS] 找不到 $INVOKE（git 没 pull 全？）" | tee -a "$LOG_FILE"
  exit 1
fi

WORKERS="$(python3 -c "
import json
d = json.load(open('$CHATS_FILE'))
for k in d:
    print(k)
")"

for worker_id in $WORKERS; do
  if [[ -n "$WORKER_FILTER" && "$worker_id" != "$WORKER_FILTER" ]]; then
    continue
  fi

  RAW_OUT="$AUDITS_DIR/${worker_id}.last_raw.txt"
  AUDIT_FILE="$AUDITS_DIR/${worker_id}.jsonl"

  RESUME_ID="$(python3 -c "
import json
d = json.load(open('$CHATS_FILE')).get('$worker_id', {})
print(d.get('session_id') or '')
")"

  if [[ -z "$RESUME_ID" ]]; then
    echo "[$TS] [$worker_id] 没有 codex session_id，跳过（先跑 kickoff）" | tee -a "$LOG_FILE"
    continue
  fi

  echo "[$TS] [$worker_id] tick → codex resume=$RESUME_ID" | tee -a "$LOG_FILE"

  set +e
  RESULT="$(python3 "$INVOKE" tick "$worker_id" \
      --workspace "$ROOT" \
      --resume-id "$RESUME_ID" \
      --prompt "tick now ($TS)" \
      --output-raw "$RAW_OUT" 2>&1)"
  EXIT=$?
  set -e

  if [[ $EXIT -ne 0 ]]; then
    echo "[$TS] [$worker_id] _invoke_manager.py exit=$EXIT result=$RESULT" | tee -a "$LOG_FILE"
    python3 -c "
import json, time
result_str = '''$RESULT'''
try:
    res = json.loads(result_str.strip().splitlines()[-1])
except Exception:
    res = {'raw_result': result_str[:500]}
entry = {
  'ts': time.time(),
  'iso': '$TS',
  'event': 'tick_cli_failed',
  'worker_id': '$worker_id',
  'backend': 'codex',
  'exit_code': $EXIT,
  'invoke_result': res,
}
with open('$ROOT/state/escalations.jsonl', 'a') as f:
    f.write(json.dumps(entry, ensure_ascii=False) + chr(10))
"
    continue
  fi

  LAST_JSON="$(python3 - "$RAW_OUT" <<'PY'
import json
import sys
path = sys.argv[1]
last = ""
for line in open(path, encoding="utf-8", errors="replace"):
    text = line.strip()
    if not (text.startswith("{") and text.endswith("}")):
        continue
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        continue
    if "action" in obj:
        last = json.dumps(obj, ensure_ascii=False)
print(last)
PY
)"
  if [[ -z "$LAST_JSON" ]]; then
    echo "[$TS] [$worker_id] manager 没输出合法 JSON audit" | tee -a "$LOG_FILE"
    python3 -c "
import json, time
entry = {
  'ts': time.time(),
  'iso': '$TS',
  'event': 'tick_no_audit_json',
  'worker_id': '$worker_id',
  'backend': 'codex',
  'raw_tail_path': '$RAW_OUT',
}
with open('$ROOT/state/escalations.jsonl', 'a') as f:
    f.write(json.dumps(entry, ensure_ascii=False) + chr(10))
"
    continue
  fi

  echo "$LAST_JSON" >> "$AUDIT_FILE"
  echo "[$TS] [$worker_id] audit: $LAST_JSON" | tee -a "$LOG_FILE"
done
