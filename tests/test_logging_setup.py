"""测试 pc_agent/main.py 的日志配置。

两个曾经的问题（都已修，这里钉住行为）：
  1. `logging.file` 是**相对路径** → 日志落点取决于从哪个目录启动，
     所以磁盘上会同时出现 `./guardian.log` 和 `pc_agent/guardian.log`。
  2. `max_size_mb` / `backup_count` 写在 config.yaml 里但**没有任何代码使用**，
     用的是不会轮转的 `FileHandler`，日志无限增长。
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytest

from pc_agent.main import setup_logging

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def root_logger():
    """保存/恢复 root logger，避免 setup_logging 的全局副作用污染其它测试。

    pytest 自己也会往 root logger 挂 handler（日志捕获），所以判断"哪个是
    setup_logging 加的"必须用**前后差集**，不能直接数文件 handler 的个数。
    """
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level

    class _Ctx:
        logger = root
        before = saved_handlers

    try:
        yield _Ctx
    finally:
        for handler in list(root.handlers):
            if handler not in saved_handlers:
                root.removeHandler(handler)
                try:
                    handler.close()
                except Exception:  # noqa: BLE001
                    pass
        root.setLevel(saved_level)


def _file_handler(ctx) -> logging.FileHandler:
    added = [h for h in ctx.logger.handlers
             if isinstance(h, logging.FileHandler) and h not in ctx.before]
    assert len(added) == 1, f"setup_logging 应当恰好新增一个文件 handler，实际 {len(added)}"
    return added[0]


class TestLoggingSetup:
    def test_uses_rotating_file_handler(self, root_logger, tmp_path):
        """必须用 RotatingFileHandler —— 否则 max_size_mb / backup_count 是哑配置。"""
        setup_logging({"logging": {
            "file": str(tmp_path / "guardian.log"),
            "max_size_mb": 3,
            "backup_count": 7,
        }})
        handler = _file_handler(root_logger)

        assert isinstance(handler, RotatingFileHandler)
        assert handler.maxBytes == 3 * 1024 * 1024
        assert handler.backupCount == 7

    def test_defaults_when_not_configured(self, root_logger, tmp_path):
        setup_logging({"logging": {"file": str(tmp_path / "guardian.log")}})
        handler = _file_handler(root_logger)
        assert handler.maxBytes == 10 * 1024 * 1024
        assert handler.backupCount == 3

    def test_relative_log_file_is_anchored_to_project_root(self, root_logger):
        """相对路径要锚定到项目根，而不是当前工作目录。"""
        setup_logging({"logging": {"file": "guardian.log"}})
        resolved = Path(_file_handler(root_logger).baseFilename)
        assert resolved.is_absolute()
        assert resolved.parent == PROJECT_ROOT

    def test_absolute_log_file_wins(self, root_logger, tmp_path):
        target = tmp_path / "custom" / "a.log"
        target.parent.mkdir(parents=True, exist_ok=True)
        setup_logging({"logging": {"file": str(target)}})
        assert Path(_file_handler(root_logger).baseFilename) == target

    def test_level_parsed(self, root_logger, tmp_path):
        setup_logging({"logging": {"level": "DEBUG", "file": str(tmp_path / "x.log")}})
        assert root_logger.logger.level == logging.DEBUG

    def test_invalid_level_falls_back_to_info(self, root_logger, tmp_path):
        """yaml 里写了非法级别不能让程序崩掉。"""
        setup_logging({"logging": {"level": "verbose", "file": str(tmp_path / "x.log")}})
        assert root_logger.logger.level == logging.INFO

    def test_missing_logging_section_uses_defaults(self, root_logger):
        setup_logging({})
        handler = _file_handler(root_logger)
        assert handler.backupCount == 3
