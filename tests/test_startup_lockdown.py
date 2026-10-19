"""测试 pc_agent/main.py 的启动熔断开关。

「熔断」这个词以前只出现在 README 里，代码里没有任何实现 —— 启动发现问题
只告警、不阻止。现在它是真的了，而且是 **opt-in**（默认关闭）：用户可能
正在调试，无脑拒绝启动会很烦人。
"""
from __future__ import annotations

import pytest

from pc_agent.main import startup_lockdown_check

CRITICAL_ISSUE = {"severity": "CRITICAL", "issue": "什么东西被改过了"}
HIGH_ISSUE = {"severity": "HIGH", "issue": "小问题"}


class _FakeAuditor:
    def __init__(self, issues, record):
        self._issues = issues
        self._record = record

    def quick_check(self):
        self._record.append("called")
        return {"ok": not self._issues, "issues": self._issues}


@pytest.fixture
def auditor(monkeypatch):
    """把 SelfAuditor 换成假的，并记录它有没有被调用。"""
    calls: list[str] = []

    def _install(issues):
        import agent.self_audit as sa

        monkeypatch.setattr(
            sa, "SelfAuditor", lambda *a, **k: _FakeAuditor(issues, calls))
        return calls

    return _install


class TestStartupLockdown:
    def test_disabled_by_default_and_does_not_even_run_the_audit(self, auditor):
        calls = auditor([CRITICAL_ISSUE])
        assert startup_lockdown_check({}) == []
        assert calls == [], "关闭时不该白跑一次自检"

    def test_explicitly_disabled(self, auditor):
        calls = auditor([CRITICAL_ISSUE])
        assert startup_lockdown_check({"agent": {"lockdown_on_critical": False}}) == []
        assert calls == []

    def test_enabled_with_critical_issue_blocks(self, auditor):
        calls = auditor([CRITICAL_ISSUE, HIGH_ISSUE])
        fatal = startup_lockdown_check({"agent": {"lockdown_on_critical": True}})
        assert calls == ["called"]
        assert fatal == [CRITICAL_ISSUE]

    def test_enabled_without_critical_issue_allows(self, auditor):
        auditor([HIGH_ISSUE])
        assert startup_lockdown_check({"agent": {"lockdown_on_critical": True}}) == []

    def test_enabled_on_clean_tree_allows(self, auditor):
        auditor([])
        assert startup_lockdown_check({"agent": {"lockdown_on_critical": True}}) == []

    def test_audit_failure_does_not_block_startup(self, monkeypatch):
        """自检自己跑不起来，不该成为拒绝启动的理由。"""
        import agent.self_audit as sa

        def _boom(*a, **k):
            raise RuntimeError("audit exploded")

        monkeypatch.setattr(sa, "SelfAuditor", _boom)
        assert startup_lockdown_check({"agent": {"lockdown_on_critical": True}}) == []

    def test_malformed_config_is_tolerated(self):
        assert startup_lockdown_check(None) == []
        assert startup_lockdown_check({"agent": None}) == []
