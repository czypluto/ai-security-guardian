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

from pc_agent.chat_window import LLMWorker  # noqa: E402

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
