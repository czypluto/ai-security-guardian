#!/usr/bin/env bash
# 后台启动本地嵌入服务（WeMM-Embedding-2B / transformers）供 embed_service 按需调用。
# 停止用 stop_embed.sh。需在 WSL 内运行。
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${EMBED_PORT:-8099}"
LOG="$HOME/guardian-embed.log"
PIDFILE="$HOME/guardian-embed.pid"

# 已在运行则直接返回
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "嵌入服务已在运行 (pid $(cat "$PIDFILE"))"
  exit 0
fi

# 端口若已被别的进程占用（例如另一个项目的嵌入服务），不要重复拉起：
# 6GB 显存上同时跑两份 WeMM-2B 会 OOM。
if ss -ltn 2>/dev/null | grep -q ":${PORT} "; then
  echo "端口 ${PORT} 已被占用——可能已有嵌入服务在跑，直接复用"
  exit 0
fi

cd "$REPO_DIR/scripts"
nohup /usr/bin/python3 -m uvicorn embed_server:app \
  --host 0.0.0.0 --port "$PORT" > "$LOG" 2>&1 &
echo $! > "$PIDFILE"
echo "嵌入服务后台启动中 (pid $(cat "$PIDFILE"))，日志: $LOG"
