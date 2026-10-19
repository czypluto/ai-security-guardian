"""
测试 agent/sandbox.py: 命令白名单/黑名单, CommandValidator, AuditLogger
"""
from __future__ import annotations

# sandbox.py has module-level `import ctypes` — must mock before import
import sys
from unittest.mock import MagicMock, patch

import pytest

_mock_ctypes = MagicMock()
_mock_ctypes.windll = MagicMock()
_mock_ctypes.windll.kernel32 = MagicMock()
_mock_ctypes.wintypes = MagicMock()
_mock_ctypes.Structure = type
sys.modules["ctypes"] = _mock_ctypes

from agent.sandbox import (  # noqa: E402  需先 mock ctypes
    BLOCKED_PATTERNS,
    DEFAULT_MAX_MEMORY_MB,
    DEFAULT_MAX_OUTPUT_BYTES,
    DEFAULT_MAX_TIME_SEC,
    SAFE_COMMANDS,
    AuditLogger,
    CommandValidator,
    SandboxExecutor,
)

# ---- CommandValidator — 命令白名单/黑名单 ----

class TestCommandValidator:
    """CommandValidator.validate() 白名单和黑名单逻辑."""

    def setup_method(self):
        self.validator = CommandValidator()

    # ── 白名单命令 ────────────────────────────────────

    def test_empty_command_blocked(self):
        allowed, reason = self.validator.validate("")
        assert allowed is False
        assert "empty" in reason.lower()

    def test_whitespace_only_blocked(self):
        allowed, reason = self.validator.validate("   ")
        assert allowed is False

    def test_safe_command_allowed(self):
        allowed, reason = self.validator.validate("ipconfig")
        assert allowed is True
        assert reason == "ok"

    def test_safe_command_with_args_allowed(self):
        allowed, reason = self.validator.validate("ipconfig /all")
        assert allowed is True
        assert reason == "ok"

    @pytest.mark.parametrize("cmd", [
        "netstat -an",
        "tasklist /v",
        "whoami",
        "ping -n 1 127.0.0.1",
        "dir /s",
    ])
    def test_known_safe_commands_allowed(self, cmd):
        allowed, _ = self.validator.validate(cmd)
        assert allowed is True

    def test_safe_prefix_command_allowed(self):
        """SAFE_PREFIXES 中的命令也应该被允许."""
        allowed, _ = self.validator.validate("wmic process list")
        assert allowed is True

    # ── 黑名单命令 ────────────────────────────────────

    def test_del_blocked(self):
        allowed, reason = self.validator.validate("del important.txt")
        assert allowed is False
        assert "blocked" in reason.lower()

    @pytest.mark.parametrize("cmd", [
        "format c:",
        "shutdown /s /t 0",
        "reg add HKLM\\...",
        "ipconfig; del file.txt",
        "ipconfig & whoami",
        "ipconfig && whoami",
    ])
    def test_known_blocked_commands(self, cmd):
        allowed, reason = self.validator.validate(cmd)
        assert allowed is False

    def test_pipe_blocked(self):
        allowed, reason = self.validator.validate("ipconfig | findstr")
        assert allowed is False
        assert "blocked" in reason.lower()

    def test_unknown_command_blocked(self):
        """不在白名单中的命令应该被拒绝（fail-closed）."""
        allowed, reason = self.validator.validate("evil_hacker_tool -x -y")
        assert allowed is False
        assert "not in safe list" in reason.lower()

    def test_case_insensitive_blocking(self):
        """黑名单检查应该大小写不敏感."""
        allowed, reason = self.validator.validate("DEL important.txt")
        assert allowed is False

    def test_exe_extension_stripped(self):
        """ipconfig.exe 应该被解析为 ipconfig."""
        allowed, _ = self.validator.validate("ipconfig.exe /all")
        assert allowed is True

    def test_full_path_stripped(self):
        """C:\\Windows\\System32\\ipconfig.exe 应该被解析."""
        allowed, _ = self.validator.validate(
            "C:\\Windows\\System32\\ipconfig.exe /all"
        )
        assert allowed is True

    # ── get_allowed_commands ──────────────────────────

    def test_get_allowed_commands(self):
        cmds = self.validator.get_allowed_commands()
        assert isinstance(cmds, list)
        assert "ipconfig" in cmds
        assert "netstat" in cmds
        assert "tasklist" in cmds


# ---- Constants 验证 ----

class TestSandboxConstants:
    """沙箱常量的范围和完整性."""

    def test_safe_commands_not_empty(self):
        assert len(SAFE_COMMANDS) > 5

    def test_blocked_patterns_include_critical(self):
        blocked_lower = [p.lower() for p in BLOCKED_PATTERNS]
        assert "del " in blocked_lower
        assert "shutdown" in blocked_lower
        assert "|" in blocked_lower
        assert "&" in blocked_lower or "&&" in map(str.lower, BLOCKED_PATTERNS)

    def test_default_timeout_reasonable(self):
        assert DEFAULT_MAX_TIME_SEC == 30

    def test_default_memory_reasonable(self):
        assert DEFAULT_MAX_MEMORY_MB == 64

    def test_default_output_reasonable(self):
        assert DEFAULT_MAX_OUTPUT_BYTES == 16384  # 16KB


# ---- SandboxExecutor.quick_check ----

class TestSandboxQuickCheck:
    """SandboxExecutor.quick_check() — 不实际执行命令."""

    def setup_method(self):
        self.sandbox = SandboxExecutor(audit=MagicMock())

    def test_quick_check_allowed(self):
        result = self.sandbox.quick_check("ipconfig")
        assert result["allowed"] is True
        assert result["reason"] == "ok"

    def test_quick_check_blocked(self):
        result = self.sandbox.quick_check("del file.txt")
        assert result["allowed"] is False

    def test_quick_check_empty(self):
        result = self.sandbox.quick_check("")
        assert result["allowed"] is False


# ---- AuditLogger ----

class TestAuditLogger:
    """AuditLogger.record() 日志格式."""

    def test_record_writes_json_line(self, tmp_path):
        log_path = tmp_path / "audit.log"
        audit = AuditLogger(str(log_path))

        with patch("agent.sandbox.datetime") as mock_dt:
            mock_dt.now.return_value = MagicMock(
                isoformat=lambda: "2025-01-01T00:00:00+00:00"
            )
            audit.record(
                execution_id="test-001",
                command="ipconfig",
                allowed=True,
                reason="completed",
                exit_code=0,
                duration_ms=150.5,
                output_size=1024,
                pid=12345,
            )

        assert log_path.exists()
        content = log_path.read_text()
        assert "test-001" in content
        assert "ipconfig" in content
        assert "completed" in content

    def test_command_truncation(self, tmp_path):
        """超长命令应该被截断到 200 字符."""
        log_path = tmp_path / "audit.log"
        audit = AuditLogger(str(log_path))

        long_cmd = "x" * 300
        with patch("agent.sandbox.datetime") as mock_dt:
            mock_dt.now.return_value = MagicMock(
                isoformat=lambda: "2025-01-01T00:00:00+00:00"
            )
            audit.record("id1", long_cmd, True, "ok")

        content = log_path.read_text()
        import json
        entry = json.loads(content.strip())
        assert len(entry["command"]) <= 200


# ---- SandboxExecutor.execute (mock subprocess) ----

class TestSandboxExecute:
    """SandboxExecutor.execute() — 通过 mock subprocess 测试执行路径."""

    def setup_method(self):
        self.sandbox = SandboxExecutor(audit=MagicMock())

    def test_blocked_command_returns_error(self):
        result = self.sandbox.execute("del bad.txt")
        assert result["success"] is False
        assert "blocked" in result["error"].lower()

    def test_empty_command_returns_error(self):
        result = self.sandbox.execute("")
        assert result["success"] is False

