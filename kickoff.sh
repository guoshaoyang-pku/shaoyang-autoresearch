#!/usr/bin/env bash
# kickoff.sh: 第一次启动 manager —— 为每个 worker 创建一个 codex session
#             并把 session_id 存到 state/manager_chats.json。
#
# 前置：
#   1. codex CLI 已装并通过 ~/.codex/config.toml 配好（参见 docs/codex_backend_recipe.md）
#   2. config.toml 已填好（特别是 [reviewer].profile / [worker].profile）
#   3. ./bootstrap.sh 已跑（state/agents.json 已存在）
#
# 用法：
#   ./kickoff.sh             # 给所有 enabled worker 创建 manager session
#   ./kickoff.sh paper_a     # 只给指定 worker 创建
#   ./kickoff.sh --reset paper_a  # 删旧 session，重新创建
#
# state/manager_chats.json schema (codex-only):
#   {
#     "<worker_id>": {
#       "backend": "codex",
#       "session_id": "<uuid>",
#       "profile": "<profile>",
#       "created_at": "<ISO8601>"
#     }
#   }

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

INVOKE="$ROOT/scripts/_invoke_manager.py"
if [[ ! -f "$INVOKE" ]]; then
  echo "找不到 $INVOKE（git 没 pull 全？）"
  exit 1
fi

RESET=0
WORKER_FILTER=""
for arg in "$@"; do
  case "$arg" in
    --reset) RESET=1 ;;
    *) WORKER_FILTER="$arg" ;;
  esac
done

CHATS_FILE="$ROOT/state/manager_chats.json"
KICKOFF_RAW_DIR="$ROOT/state/manager_kickoff_raw"
mkdir -p "$ROOT/state" "$KICKOFF_RAW_DIR"

# 读 [reviewer] 段。codex-only：profile + cli_path（model 字段已废弃）
PROFILE="$(python3 -c "
import tomllib
cfg = tomllib.load(open('config.toml','rb'))
rv = cfg.get('reviewer', {})
backend = (rv.get('backend') or 'codex').strip().lower()
if backend != 'codex':
    raise SystemExit(f'[reviewer].backend = {backend!r} 已不支持；仅 codex')
print(rv.get('profile', 'high'))
")"
CLI_PATH="$(python3 -c "
import tomllib
cfg = tomllib.load(open('config.toml','rb'))
rv = cfg.get('reviewer', {})
print(rv.get('cli_path', 'codex'))
")"

echo "Manager backend: codex (profile=$PROFILE) via $CLI_PATH"

if ! command -v "$CLI_PATH" >/dev/null 2>&1; then
  echo "✗ $CLI_PATH 不在 PATH（未装？参见 docs/codex_backend_recipe.md）"
  exit 1
fi
if ! "$CLI_PATH" --version >/dev/null 2>&1; then
  echo "✗ $CLI_PATH --version 失败（包是否损坏？）"
  exit 1
fi

if [[ -f "$CHATS_FILE" ]]; then
  EXISTING="$(cat "$CHATS_FILE")"
else
  EXISTING="{}"
fi

WORKERS_JSON="$(python3 -c '
import json, tomllib
with open("config.toml","rb") as f:
    cfg = tomllib.load(f)
out = []
base = cfg["worker"].get("worktree_base", "main")
prefix = cfg["worker"].get("worker_branch_prefix", "auto-worker-")
for w in cfg["workers"]:
    if not w.get("enabled", True):
        continue
    out.append({
        "id": w["id"],
        "label": w["label"],
        "rules_paths": w["rules_paths"],
        "subdir": w.get("subdir", ""),
        "branch": f"{prefix}{w['id']}",
        "base": base,
    })
print(json.dumps(out))
')"

NEW_CHATS="$EXISTING"

while IFS= read -r worker_b64; do
  worker_json="$(echo "$worker_b64" | base64 -D 2>/dev/null || echo "$worker_b64" | base64 -d)"
  worker_id="$(echo "$worker_json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"

  if [[ -n "$WORKER_FILTER" && "$worker_id" != "$WORKER_FILTER" ]]; then
    continue
  fi

  EXISTS_INFO="$(echo "$EXISTING" | python3 -c "
import json, sys
d = json.load(sys.stdin)
e = d.get('$worker_id', {})
print(e.get('session_id') or '')
")"
  if [[ -n "$EXISTS_INFO" && $RESET -eq 0 ]]; then
    echo "[$worker_id] 已有 codex session=$EXISTS_INFO（--reset 重建）"
    continue
  fi

  INITIAL_PROMPT_FILE="$(mktemp)"
  RAW_OUT_FILE="$KICKOFF_RAW_DIR/${worker_id}.kickoff.txt"
  RESULT_FILE="$(mktemp)"
  trap "rm -f '$INITIAL_PROMPT_FILE' '$RESULT_FILE'" EXIT

  python3 <<PY > "$INITIAL_PROMPT_FILE"
import json, pathlib, os
worker = json.loads('''$worker_json''')
mgr_md = pathlib.Path("prompts/manager.md").read_text()
def resolve(p):
    path = pathlib.Path(os.path.expanduser(p))
    return path if path.is_absolute() else pathlib.Path.cwd() / path
rules_text = "\n\n".join(resolve(p).read_text() for p in worker["rules_paths"])

print(f"""# 你被分配管理的 Worker

worker_id: {worker['id']}
label:     {worker['label']}
repo subdir: {worker['subdir']}
branch:    {worker['branch']}
base:      {worker['base']}

# 你的 Persona + 工作流程

{mgr_md}

# 你管的 Worker 的 Hard Rules（每次 review 必须复习）

{rules_text}

---

# 初始化

读完上面所有内容，回答以下 3 个问题确认你理解了，然后等待第一次 kick：

1. 你管的是哪个 worker？
2. 你的工具集是什么？（列出 mgr 命令）
3. 一次 tick 的 5 步流程是什么？

回答完后，**最后一行**输出这条 JSON 表示初始化成功：
{{"init_ok": true, "worker": "{worker['id']}"}}
""")
PY

  echo "[$worker_id] 创建新 codex session（profile=$PROFILE）..."

  set +e
  python3 "$INVOKE" kickoff "$worker_id" \
    --workspace "$ROOT" \
    --prompt-file "$INITIAL_PROMPT_FILE" \
    --output-raw "$RAW_OUT_FILE" > "$RESULT_FILE"
  EXIT=$?
  set -e

  RESULT_JSON="$(cat "$RESULT_FILE")"

  if [[ $EXIT -ne 0 ]]; then
    echo "[$worker_id] ✗ kickoff 失败（exit=$EXIT）"
    echo "  invoke 返回: $RESULT_JSON"
    echo "  raw 输出（前 60 行）已保存到 $RAW_OUT_FILE :"
    head -60 "$RAW_OUT_FILE" 2>/dev/null || true
    continue
  fi

  SESSION_ID="$(python3 -c "
import json
d = json.loads('''$RESULT_JSON''')
print(d.get('session_id') or '')
")"

  if [[ -z "$SESSION_ID" ]]; then
    echo "[$worker_id] ✗ invoke 返回里没 session_id"
    echo "  result: $RESULT_JSON"
    continue
  fi

  echo "[$worker_id] ✓ codex session_id = $SESSION_ID"

  NEW_CHATS="$(echo "$NEW_CHATS" | python3 -c "
import json, sys
d = json.load(sys.stdin)
d['$worker_id'] = {
    'backend': 'codex',
    'session_id': '$SESSION_ID',
    'profile': '$PROFILE',
    'created_at': '$(date -Iseconds)',
}
print(json.dumps(d, indent=2, ensure_ascii=False))
")"

done < <(echo "$WORKERS_JSON" | python3 -c '
import json, sys, base64
ws = json.load(sys.stdin)
for w in ws:
    print(base64.b64encode(json.dumps(w).encode()).decode())
')

echo "$NEW_CHATS" > "$CHATS_FILE"
echo ""
echo "完成。state/manager_chats.json 已更新："
cat "$CHATS_FILE"
echo ""
echo "下一步："
echo "  ./tick.sh                     # 手动跑一次 tick 测试"
echo "  ./scripts/install_launchd.sh  # 装 launchd 自动每 5min tick (macOS)"
