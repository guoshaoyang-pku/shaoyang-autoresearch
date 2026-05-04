#!/usr/bin/env bash
# Bootstrap (架构 Y, local worker)：
#   1. 为每个 worker 创建 git worktree（路径 ~/.cursor/worktrees/<repo>/<worker_id>）
#   2. 在 worktree 里 checkout 一个 worker 专属 branch（避免和你手动操作冲突）
#   3. 把 worktree_path / branch 写入 state/workers/<id>/
#
# 用法：
#   ./bootstrap.sh                # 所有 enabled worker
#   ./bootstrap.sh paper_a        # 只指定 worker
#   ./bootstrap.sh --force        # 即使已存在也重建（删 worktree、重 checkout）

set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f config.toml ]]; then
  echo "config.toml 不存在，先 cp config.example.toml config.toml"
  exit 1
fi

FORCE=0
WORKER_FILTER=""
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    *) WORKER_FILTER="$arg" ;;
  esac
done

python3 - "$FORCE" "$WORKER_FILTER" <<'PY'
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
from lib.state import expand, workers_root
from lib.codex_worker import CodexWorker

force = bool(int(sys.argv[1]))
worker_filter = sys.argv[2] if len(sys.argv) > 2 else ""

with open("config.toml", "rb") as f:
    cfg = tomllib.load(f)

worker_cfg = cfg["worker"]
backend = (worker_cfg.get("backend") or "codex").strip().lower()
if backend != "codex":
    raise SystemExit(f"[worker].backend = {backend!r} 已不支持；仅 codex")

worker_profile = worker_cfg.get("profile", "high")
worker_cli_path = worker_cfg.get("cli_path", "codex")
local_repo_path = expand(worker_cfg["local_repo_path"])
worktree_base = worker_cfg.get("worktree_base", "paper/neurips2026-draft")
worker_branch_prefix = worker_cfg.get("worker_branch_prefix", f"{worktree_base}-worker-")

worktrees_root = expand(f"~/.cursor/worktrees/{local_repo_path.name}")
worktrees_root.mkdir(parents=True, exist_ok=True)

print(f"Local repo: {local_repo_path}")
print(f"Worktree root: {worktrees_root}")
print(f"Worktree base ref: {worktree_base}")
print(f"Worker backend: codex (profile={worker_profile}) via {worker_cli_path}")
print()

def git(*args, cwd=None, check=True):
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd or local_repo_path),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} (cwd={cwd}) failed:\n{proc.stderr}")
    return proc.stdout.strip()

# 验证 base ref 存在
try:
    head = git("rev-parse", worktree_base)
    print(f"Base {worktree_base} HEAD = {head}")
except RuntimeError as e:
    print(f"✗ {e}")
    sys.exit(1)

for w in cfg["workers"]:
    if not w.get("enabled", True):
        continue
    if worker_filter and w["id"] != worker_filter:
        continue

    wid = w["id"]
    branch = f"{worker_branch_prefix}{wid}"
    worktree_path = worktrees_root / wid

    print(f"\n=== {wid} ({w['label']}) ===")

    if worktree_path.exists():
        if force:
            print(f"  --force: 删旧 worktree {worktree_path}")
            try:
                git("worktree", "remove", "--force", str(worktree_path))
            except RuntimeError as e:
                print(f"  warn: {e}")
                # 兜底：手动删
                import shutil
                if worktree_path.exists():
                    shutil.rmtree(worktree_path)
            try:
                git("branch", "-D", branch, check=False)
            except Exception:
                pass
        else:
            print(f"  worktree 已存在: {worktree_path}（--force 重建）")
            # 仍然写入 state
            cw = CodexWorker(wid, cli_path=worker_cli_path, profile=worker_profile)
            cw.worktree_path = str(worktree_path)
            cw.branch = branch
            print(f"  → state/workers/{wid}/{{worktree_path,branch}} 已写入")
            continue

    # 创建 worktree + branch
    print(f"  创建 worktree: {worktree_path}")
    print(f"  分支: {branch} (基于 {worktree_base})")

    # 检查 branch 是否已存在
    existing_branches = git("branch", "--list", branch, check=False)
    if existing_branches.strip():
        # 已有 branch，复用
        git("worktree", "add", str(worktree_path), branch)
    else:
        git("worktree", "add", "-b", branch, str(worktree_path), worktree_base)

    cw = CodexWorker(wid, cli_path=worker_cli_path, profile=worker_profile)
    cw.worktree_path = str(worktree_path)
    cw.branch = branch
    print(f"  ✓ state/workers/{wid}/ 已初始化")

print()
print("完成。下一步：")
print("  ./kickoff.sh             # 创建 manager chat sessions（manager LLM 持久化记忆）")
print("  ./tick.sh                # 手动跑一次 manager tick")
print("  ./scripts/install_launchd.sh   # 装 launchd 自动调度")
print()
print("查看 worker：")
print("  ./mgr workers")
print("  ./mgr status paper_a")
PY
