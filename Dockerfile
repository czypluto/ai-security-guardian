# ============================================================
# AI Security Guardian — Docker 镜像
# ============================================================
# 多阶段构建:
#   1. builder  — poetry 安装依赖 (不含 Windows 专用包)
#   2. runtime  — 最小化运行镜像
# ============================================================

# ── Stage 1: Builder ────────────────────────────────────────
FROM python:3.10-slim AS builder

# 系统依赖 (编译工具)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# 安装 Poetry
ENV POETRY_HOME="/opt/poetry" \
    POETRY_VERSION="2.4.1"
RUN curl -sSL https://install.python-poetry.org | python3 - \
    && ln -s /opt/poetry/bin/poetry /usr/local/bin/poetry

WORKDIR /app

# 复制 Poetry 配置 (利用 Docker 缓存层)
COPY pyproject.toml poetry.lock poetry.toml ./

# 安装依赖 (跳过 Windows 专用和可选组)
# pywin32 通过 sys_platform=="win32" marker 在 Linux 上自动跳过
# 清华镜像源已在 pyproject.toml [[tool.poetry.source]] 中全局配置
RUN poetry install \
    --without tray,gui \
    --no-root \
    --no-interaction \
    --no-ansi

# ── Stage 2: Runtime ────────────────────────────────────────
FROM python:3.10-slim AS runtime

LABEL org.opencontainers.image.title="AI Security Guardian"
LABEL org.opencontainers.image.description="AI 网络安全管家 — Autonomous PC Agent with ESP32 hardware isolation"
LABEL org.opencontainers.image.url="https://github.com/czypluto/ai-security-guardian"
LABEL org.opencontainers.image.licenses="MIT"

# 创建非 root 用户
RUN groupadd -r guardian && useradd -r -g guardian -d /app guardian

WORKDIR /app

# 从 builder 复制虚拟环境
COPY --from=builder /app/.venv /app/.venv

# 复制源码
COPY agent/         /app/agent/
COPY pc_agent/      /app/pc_agent/
COPY skills/        /app/skills/
COPY agent_cli.py   /app/agent_cli.py
COPY pyproject.toml /app/pyproject.toml

# 确保虚拟环境在 PATH 中
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# 创建数据目录
RUN mkdir -p /app/data /app/logs && \
    chown -R guardian:guardian /app

# 切换到非 root 用户
USER guardian

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import agent; print('OK')" || exit 1

# 默认入口: CLI Agent
ENTRYPOINT ["python", "agent_cli.py"]
CMD ["--help"]
