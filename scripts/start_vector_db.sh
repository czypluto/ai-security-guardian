#!/usr/bin/env bash
# 启动 Milvus + Qdrant 向量库容器 (Windows Git Bash / macOS / Linux 均可用)
# 用法: bash scripts/start_vector_db.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/vector_db/docker-compose.yml"

echo "==> 检查 Docker daemon..."
if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon 未运行，尝试启动 Docker Desktop..."
  case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*)
      "/c/Program Files/Docker/Docker/Docker Desktop.exe" & disown || true
      ;;
    Darwin)
      open -a Docker || true
      ;;
  esac
  for i in $(seq 1 120); do
    if docker info >/dev/null 2>&1; then
      echo "Docker 已就绪 (${i}s)。"
      break
    fi
    sleep 1
  done
  if ! docker info >/dev/null 2>&1; then
    echo "错误: Docker 120s 内未就绪，请手动启动 Docker Desktop 后重试。"
    exit 1
  fi
fi

echo "==> 启动 Milvus + Qdrant 容器 (首次会拉取镜像，可能需要几分钟)..."
docker compose -f "$COMPOSE_FILE" up -d

echo "==> 等待服务就绪..."
READY=0
for i in $(seq 1 120); do
  MV_OK=0; QD_OK=0
  (echo >/dev/tcp/localhost/19530) 2>/dev/null && MV_OK=1
  (echo >/dev/tcp/localhost/6333)  2>/dev/null && QD_OK=1
  if [ "$MV_OK" = "1" ] && [ "$QD_OK" = "1" ]; then
    READY=1
    echo "Milvus(:19530) 与 Qdrant(:6333) 已就绪 (${i}x2s)。"
    break
  fi
  sleep 2
done

if [ "$READY" != "1" ]; then
  echo "警告: 等待超时，请稍后运行 'docker compose -f $COMPOSE_FILE ps' 查看状态。"
fi

echo
echo "已启动。停止服务: docker compose -f $COMPOSE_FILE down"
echo "数据卷: $SCRIPT_DIR/vector_db/volumes/"
echo "下一步: 嵌入服务无需手起 —— agent/embed_service.py 会在首次嵌入时按需拉起"
echo "        手动启动: wsl -e bash -lc 'bash scripts/run_embed.sh'"
echo "        客户端 SDK: pip install pymilvus qdrant-client"
