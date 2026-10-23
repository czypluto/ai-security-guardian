"""测试 pc_agent/chat_window.py 的跨线程审批握手。

GUI 组件整体不在 CI 覆盖范围内（CI 用 `--without tray,gui,kb`，不装 PyQt5），
所以这里用 importorskip 跳过：装了 PyQt5 的本地环境会真的跑。

要验证的核心是**回程不经 Qt 信号**这一决定：QThread 对象的线程亲和性是创建它的
线程（主线程），「主线程 -> worker 的槽」的 queued connection 会在主线程执行，
用它回传审批结果会得到一个在主线程里空等的假象。改用 threading.Event + 普通方法
之后，这条链路才真的能把结果送回 worker 线程。
"""
from __future__ import annotations

import os
import threading
import time

import pytest

# 无头环境也要能建 QApplication
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt5", reason="GUI 测试需要 PyQt5（CI 不安装 gui 组）")

from PyQt5.QtWidgets import QApplication  # noqa: E402

from pc_agent.chat_window import HistoryDialog, LLMWorker  # noqa: E402

PAYLOAD = {
    "kind": "approval_request",
    "tool": "run_command",
    "arguments": {"command": "ipconfig"},
    "risk_level": "caution",
    "tool_call_id": "c1",
    "message": "是否允许执行 run_command?",
}


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _wait_until(predicate, timeout=5.0):
    """等待条件成立，同时泵 Qt 事件。

    必须泵事件：approval_request 从普通 Python 线程发出、接收方是主线程亲和的
    对象，Qt 因此走 **queued connection** —— 没有事件循环就永远不会派发。
    真实 GUI 里这一步由 QApplication.exec_() 完成。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        QApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


class _FakeLLM:
    available_count = 1


class FakeAgent:
    """产出预设事件的假 AgentCore，用来验证 worker 的事件翻译。"""

    def __init__(self, events):
        self._events = events
        self.llm = _FakeLLM()
        self.approval_callback = None
        self.ephemeral_args = []

    def run_stream(self, message, ephemeral=False):
        self.ephemeral_args.append(ephemeral)
        yield from self._events


class TestEventTranslation:
    """LLMWorker 把图的 custom 事件翻译成 Qt 信号。

    打字机效果就靠这里：图把文本分多次给（{type: text, content: 增量}），
    worker 必须逐块 emit，而不是攒成一段一次性发。
    """

    def test_incremental_text_becomes_multiple_signals(self, qapp):
        agent = FakeAgent([
            {"type": "text", "content": "安"},
            {"type": "text", "content": "全"},
        ])
        worker = LLMWorker(agent, message="状态")
        chunks = []
        results = []
        worker.streaming.connect(chunks.append)
        worker.finished.connect(lambda text, ok: results.append((text, ok)))

        worker.run()   # 直接跑，不启线程：主线程内直连信号会同步派发

        assert chunks == ["安", "全"], "文本没有被逐块发出"
        assert results == [("安全", True)]

    def test_tool_events_become_signals(self, qapp):
        agent = FakeAgent([
            {"type": "tool_start", "name": "scan_network", "arguments": {"deep": True}},
            {"type": "tool_result", "name": "scan_network", "result": '{"ok":true}'},
            {"type": "text", "content": "完成"},
        ])
        worker = LLMWorker(agent, message="扫描")
        calls, results_evt, done = [], [], []
        worker.tool_call_signal.connect(lambda n, a: calls.append((n, a)))
        worker.tool_result_signal.connect(lambda n, r: results_evt.append((n, r)))
        worker.finished.connect(lambda t, ok: done.append((t, ok)))

        worker.run()

        assert calls == [("scan_network", '{"deep": true}')]
        assert results_evt[0][0] == "scan_network"
        assert done == [("完成", True)]

    def test_error_event_fails_without_raising(self, qapp):
        agent = FakeAgent([{"type": "error", "content": "API rate limit exceeded"}])
        worker = LLMWorker(agent, message="x")
        done = []
        worker.finished.connect(lambda t, ok: done.append((t, ok)))

        worker.run()

        assert done and done[0][1] is False
        assert "API rate limit exceeded" in done[0][0]

    def test_ephemeral_flag_reaches_the_agent(self, qapp):
        agent = FakeAgent([{"type": "text", "content": "报告"}])
        worker = LLMWorker(agent, message="生成报告", ephemeral=True)
        worker.finished.connect(lambda t, ok: None)

        worker.run()

        assert agent.ephemeral_args == [True]

    def test_approval_callback_is_cleared_after_run(self, qapp):
        agent = FakeAgent([{"type": "text", "content": "ok"}])
        worker = LLMWorker(agent, message="x")
        worker.finished.connect(lambda t, ok: None)

        worker.run()

        assert agent.approval_callback is None, "跑完后必须摘掉回调，避免悬空引用"


class TestApprovalHandshake:
    def test_request_is_emitted_and_result_returned(self, qapp):
        worker = LLMWorker(agent=None)
        received = []
        worker.approval_request.connect(
            lambda rid, payload: received.append((rid, payload)))

        box = {}

        def _run():
            box["decision"] = worker._ask_approval(dict(PAYLOAD))

        t = threading.Thread(target=_run, daemon=True)
        t.start()

        assert _wait_until(lambda: len(received) == 1), "审批请求没有被发出来"
        request_id, payload = received[0]
        assert payload["tool"] == "run_command"
        assert payload["arguments"] == {"command": "ipconfig"}

        # 请求发出后，worker 应处于「等待人工」状态 —— 看门狗靠这个避免误杀
        assert worker.waiting_for_approval is True

        # 主线程侧：普通方法，不是 Qt 槽
        worker.deliver_approval(request_id, {"approved": True, "reason": "gui_user"})

        t.join(timeout=5)
        assert not t.is_alive(), "deliver_approval 之后 worker 仍在等待"
        assert box["decision"] == {"approved": True, "reason": "gui_user"}
        assert worker.waiting_for_approval is False

    def test_denial_is_returned_as_a_decision_not_an_exception(self, qapp):
        worker = LLMWorker(agent=None)
        received = []
        worker.approval_request.connect(
            lambda rid, payload: received.append(rid))
        box = {}

        def _run():
            box["decision"] = worker._ask_approval(dict(PAYLOAD))

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        assert _wait_until(lambda: len(received) == 1)
        worker.deliver_approval(received[0], {"approved": False, "reason": "gui_denied"})
        t.join(timeout=5)

        assert box["decision"]["approved"] is False
        assert box["decision"]["reason"] == "gui_denied"

    def test_cancel_interrupts_the_wait(self, qapp):
        """取消要能在等待审批期间生效，而不是等到超时。"""
        worker = LLMWorker(agent=None)
        received = []
        worker.approval_request.connect(lambda rid, payload: received.append(rid))

        import pc_agent.chat_window as cw
        box = {}

        def _run():
            try:
                worker._ask_approval(dict(PAYLOAD))
                box["raised"] = False
            except cw._WorkerCancelled:
                box["raised"] = True

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        assert _wait_until(lambda: len(received) == 1)

        worker.request_cancel()
        t.join(timeout=5)
        assert box.get("raised") is True, "取消没有中断等待"
        assert worker.waiting_for_approval is False

    def test_progress_timer_reset(self):
        worker = LLMWorker(agent=None)
        worker._start_time = time.time() - 100
        worker._last_progress = time.time() - 100
        assert worker.seconds_since_progress > 90
        worker.note_progress()
        assert worker.seconds_since_progress < 1


class TestHistoryDialog:
    def test_selects_conversation(self, qapp):
        conversations = [{
            "conversation_id": "conv-1",
            "title": "防火墙检查",
            "updated_at": "2026-10-23T00:00:00",
            "message_count": 6,
        }]
        dialog = HistoryDialog(conversations)
        assert dialog.list.count() == 1
        dialog.list.setCurrentRow(0)
        dialog._accept_selected()
        assert dialog.selected_id == "conv-1"
