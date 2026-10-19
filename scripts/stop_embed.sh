#!/usr/bin/env bash
# 停止本地嵌入服务（释放显存、模型回磁盘）。需在 WSL 内运行。
set -uo pipefail

PIDFILE="$HOME/guardian-embed.pid"

if [ -f "$PIDFILE" ]; then
  pid="$(cat "$PIDFILE")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    sleep 2
    kill -9 "$pid" 2>/dev/null || true
    echo "嵌入服务已停止 (pid $pid)"
  else
    echo "嵌入服务进程已不存在 (pid $pid)"
  fi
  rm -f "$PIDFILE"
  exit 0
fi

if pkill -f "uvicorn embed_server" 2>/dev/null; then
  echo "嵌入服务已停止（按进程名匹配）"
else
  echo "嵌入服务未在运行"
fi
