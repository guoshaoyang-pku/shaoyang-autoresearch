#!/usr/bin/env bash
# 装 launchd job：每 N 分钟跑一次 tick.sh（驱动 manager LLM 巡检）。
#
# 用法：
#   ./scripts/install_launchd.sh             # 装
#   ./scripts/install_launchd.sh --uninstall # 卸

set -euo pipefail

LABEL="com.user.cursor-manager.tick"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TICK="$ROOT/tick.sh"
LOG_OUT="$ROOT/state/launchd.out.log"
LOG_ERR="$ROOT/state/launchd.err.log"
INTERVAL=300  # 5 分钟

if [[ "${1:-}" == "--uninstall" ]]; then
  launchctl unload "$PLIST_PATH" 2>/dev/null || true
  rm -f "$PLIST_PATH"
  echo "已卸载 launchd job: $LABEL"
  exit 0
fi

mkdir -p "$(dirname "$LOG_OUT")"

# launchd 不继承用户 shell 的 PATH，要把 codex 路径塞进去
EXTRA_PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${TICK}</string>
  </array>
  <key>StartInterval</key><integer>${INTERVAL}</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>${LOG_OUT}</string>
  <key>StandardErrorPath</key><string>${LOG_ERR}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>${EXTRA_PATH}</string>
    <key>HOME</key><string>${HOME}</string>
  </dict>
  <key>WorkingDirectory</key><string>${ROOT}</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"
echo "已装 launchd job: $LABEL"
echo "  每 ${INTERVAL}s 跑一次 tick.sh"
echo "  log: tail -f $LOG_OUT $LOG_ERR"
echo "  audit: tail -f state/manager_audits/*.jsonl"
echo "  卸载: $0 --uninstall"
echo ""
echo "前置：codex CLI 必须可用（codex --version 应当通），并已通过"
echo "~/.codex/config.toml 配置好 profile（参见 docs/codex_backend_recipe.md）。"
