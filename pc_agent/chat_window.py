"""
AI 安全对话窗口 - Chat Window
与 desktop_gui 同一套设计语言

功能:
  - ReAct 智能对话 (Think -> Act -> Observe -> Respond)
  - 工具调用 (安全扫描/威胁检测/漏洞检查)
  - 流式输出
  - 对话历史
"""

import json
import logging
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

try:
    from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
    from PyQt5.QtGui import (
        QColor,
        QFont,
    )
    from PyQt5.QtWidgets import (
        QApplication,
        QDialog,
        QFrame,
        QHBoxLayout,
        QLabel,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
    HAS_PYQT5 = True
except ImportError:
    HAS_PYQT5 = False
    QApplication = QDialog = QWidget = QFrame = QLabel = object
    QVBoxLayout = QHBoxLayout = QPushButton = QTextEdit = object
    QScrollArea = QMessageBox = object
    QThread = pyqtSignal = object
    QTimer = object
    QFont = QColor = object
    Qt = type('Qt', (), {})()

# Agent module integration (tools + llm)
_AGENT_ROOT = str(Path(__file__).parent.parent)
if _AGENT_ROOT not in sys.path:
    sys.path.insert(0, _AGENT_ROOT)

try:
    from agent.core import AgentCore  # noqa: F401  用作可用性探测
    HAS_AGENT = True
except ImportError:
    HAS_AGENT = False

try:
    from agent.config import LLMProvider  # noqa: F401  用作可用性探测
    from agent.llm import LLMRouter  # noqa: F401
    HAS_ROUTER = True
except ImportError:
    HAS_ROUTER = False

try:
    import agent.knowledge_base as _kb_module  # noqa: F401  仅探测模块可用性
    HAS_KB = True
except ImportError:
    HAS_KB = False


# 颜色常量（与 desktop_gui 一致）
COLORS = {
    'bg_primary':     '#0d0f12',   # 主背景
    'bg_card':        '#15181d',   # 卡片背景
    'bg_card_hover':  '#1a1e24',   # 卡片悬停
    'bg_inset':       '#1c2026',   # 内嵌区域
    'border':         '#22262e',   # 极淡边框
    'border_focus':   '#2d3340',   # 聚焦边框
    'accent':         '#3b82f6',   # 主强调色 - 沉稳蓝
    'accent_soft':    '#1e3a5f',   # 柔和蓝
    'safe':           '#10b981',   # 安全 - 翡翠绿
    'warning':        '#f59e0b',   # 警告 - 琥珀
    'danger':         '#ef4444',   # 危险 - 红
    'text_primary':   '#e4e7eb',   # 主文字
    'text_secondary': '#8b919e',   # 次要文字
    'text_muted':     '#5c6370',   # 静默文字
    'user_bubble':    '#1e2734',   # 用户气泡 - 深蓝灰
    'ai_bubble':      '#15181d',   # AI 气泡 - 同卡片
    'system_bubble':  '#121612',   # 系统气泡 - 微绿调
    'white':          '#ffffff',
}


# AI 安全管家系统提示词 (ReAct + Tools)
SECURITY_AGENT_PROMPT = """你是"安小盾"，一个 AI 网络安全管家，运行在用户的 Windows PC 上。

## 身份与性格
- 专业可靠的安全专家，带一点可爱的二次元风格
- 用中文回复，保持专业但不失亲切，可偶尔使用颜文字
- 回复简洁，一般不超过 150 字

## 核心能力 — 你可以直接调用工具
你拥有实时系统安全工具，**务必主动使用它们来回答问题**：
- **scan_network** — 扫描活跃网络连接，检测可疑 IP 和恶意端口（C2、后门）
- **scan_processes** — 扫描运行中的进程，识别可疑/恶意软件
- **check_firewall** — 检查 Windows 防火墙和 Defender 状态
- **read_security_logs** — 读取 Windows 安全事件日志
- **security_summary** — 获取综合安全摘要和风险等级
- **get_system_state** — 获取 CPU/内存/磁盘使用率
- **get_listening_ports** — 列出所有开放监听端口
- **run_command** — 执行安全诊断命令（ipconfig, netstat, tasklist 等）
- **threat_check_ip** — 通过 AlienVault OTX 检查 IP 信誉
- **cve_search** — 搜索 CVE 漏洞信息

## 工具使用规则
1. **用户问安全状态 → 先调用 scan_network + check_firewall + security_summary**
2. **用户问可疑进程 → 调用 scan_processes**
3. **用户问端口/防火墙 → 调用 check_firewall + get_listening_ports**
4. **不要猜测，用工具获取真实数据后回答**
5. 工具结果可能较长，你只需提取关键信息回复用户
6. 如果检测到威胁，说明严重等级和建议的应对措施"""


# 协作取消用的内部信号
class _WorkerCancelled(Exception):
    """worker 收到协作取消请求。不是错误，不进错误路径。"""


# LLM 后台工作线程 — 驱动 AgentCore 的状态图
class LLMWorker(QThread):
    """驱动 AgentCore 的状态图，把事件翻译成 Qt 信号。

    这里曾经自己实现了一整套 ReAct 循环 —— 与 agent/core.py 那份是**并行的
    第二套**，两边各写一份 system prompt、各自维护历史。现在两份合一：
    GUI 与 CLI 跑的是同一张 LangGraph 状态图（见 agent/graph.py）。

    审批走 LangGraph 的 interrupt()：图在 approval 节点挂起并返回，worker 通过
    approval_request 信号把请求交给主线程弹对话框，再等 threading.Event 被 set。

    回程刻意**不用 Qt 信号**：QThread 对象的线程亲和性是**创建它的线程**（主线程），
    所以「主线程 -> worker 的槽」这种 queued connection 会在主线程执行，而不是在
    worker 线程 —— 用它回传审批结果会得到一个在主线程里空等的假象。改用普通
    Python 方法（deliver_approval）+ threading.Event 规避整个问题。
    """

    finished = pyqtSignal(str, bool)          # (final_text, success)
    streaming = pyqtSignal(str)               # 文本增量
    tool_call_signal = pyqtSignal(str, str)   # (tool_name, args_summary)
    tool_result_signal = pyqtSignal(str, str) # (tool_name, result_summary)
    approval_request = pyqtSignal(str, dict)  # (request_id, payload) — 新增

    MAX_TOOL_ITERATIONS = 5
    # 语义改为「**无进展**时长」：每收到一个事件就重置。等待人工审批期间
    # 由 _ask_approval 自己的轮询维持，不走这个预算。
    TIMEOUT_SECONDS = 60
    APPROVAL_TIMEOUT = 300

    def __init__(self, agent, message: str = "", parent=None, ephemeral: bool = False):
        super().__init__(parent)
        self.agent = agent
        self.message = message
        self.ephemeral = ephemeral
        self._start_time = 0.0
        self._last_progress = 0.0
        self._cancelled = threading.Event()
        self._approval_lock = threading.Lock()
        self._approval_events: Dict[str, threading.Event] = {}
        self._approval_results: Dict[str, dict] = {}
        self._waiting_for_approval = threading.Event()

    # ---- 主线程调用（普通方法，不是 Qt 槽）----

    @property
    def waiting_for_approval(self) -> bool:
        return self._waiting_for_approval.is_set()

    @property
    def seconds_since_progress(self) -> float:
        return time.time() - (self._last_progress or self._start_time)

    def note_progress(self):
        """把「无进展」计时归零。主线程在弹完审批框后调用。"""
        self._last_progress = time.time()

    def deliver_approval(self, request_id: str, decision: dict):
        """主线程在用户点了对话框之后调用。"""
        with self._approval_lock:
            self._approval_results[request_id] = decision
            event = self._approval_events.pop(request_id, None)
        if event:
            event.set()   # Event.set 本身线程安全

    def request_cancel(self):
        """协作式取消：worker 会在下一个检查点退出，不会撕裂 SQLite 写入。"""
        self._cancelled.set()

    # ---- worker 线程 ----

    def run(self):
        self._start_time = time.time()
        self._last_progress = self._start_time

        if self.agent is None:
            self.finished.emit(
                "Agent 未就绪。\n请检查 config.yaml 中的 llm 配置。", False)
            return

        if getattr(self.agent.llm, "available_count", 0) == 0:
            self.finished.emit(
                "未配置 AI 模型。请在 config.yaml 中配置 DeepSeek API Key。\n\n"
                "获取 Key: https://platform.deepseek.com\n"
                "配置后在 config.yaml 的 llm.deepseek 填入 api_key",
                False)
            return

        self.agent.approval_callback = self._ask_approval
        try:
            self._drive()
        except _WorkerCancelled:
            self.finished.emit("已取消。", False)
        except Exception as e:
            import traceback
            self.finished.emit(f"AI 异常: {e}\n{traceback.format_exc()}", False)
        finally:
            self.agent.approval_callback = None
            self._waiting_for_approval.clear()

    def _drive(self):
        full_text = ""
        for event in self.agent.run_stream(self.message, ephemeral=self.ephemeral):
            if self._cancelled.is_set():
                raise _WorkerCancelled()
            self._last_progress = time.time()

            etype = event.get("type", "")
            if etype == "text":
                chunk = event.get("content", "")
                full_text += chunk
                self.streaming.emit(chunk)
            elif etype == "tool_start":
                self.tool_call_signal.emit(
                    event.get("name", "?"),
                    json.dumps(event.get("arguments") or {}, ensure_ascii=False)[:120])
            elif etype == "tool_result":
                self.tool_result_signal.emit(
                    event.get("name", "?"), str(event.get("result", ""))[:300])
            elif etype == "error":
                self.finished.emit(
                    f"⚠️ {event.get('content', 'AI 服务异常')}\n\n请检查网络连接后重试。",
                    False)
                return

        if full_text.strip():
            self.finished.emit(full_text.strip(), True)
        else:
            self.finished.emit("[已达到最大工具调用次数，请重新提问]", False)

    def _ask_approval(self, payload: dict) -> dict:
        """在 worker 线程上被 AgentCore 调用；把问题推给主线程并等待。"""
        request_id = uuid.uuid4().hex
        event = threading.Event()
        with self._approval_lock:
            self._approval_events[request_id] = event

        self._waiting_for_approval.set()
        self.approval_request.emit(request_id, payload)   # 跨线程：自动 queued 到主线程

        deadline = time.time() + self.APPROVAL_TIMEOUT
        try:
            while not event.wait(0.25):
                if self._cancelled.is_set():
                    raise _WorkerCancelled()
                if time.time() > deadline:
                    # 超时按拒绝处理 —— fail-closed
                    return {"approved": False, "reason": "approval_timeout"}
        finally:
            self._waiting_for_approval.clear()
            with self._approval_lock:
                self._approval_events.pop(request_id, None)

        with self._approval_lock:
            return self._approval_results.pop(
                request_id, {"approved": False, "reason": "unknown"})


# 消息气泡组件
class ChatBubble(QFrame):
    """单条聊天消息气泡 — 无边框，纯色块区分角色"""

    def __init__(self, text: str, role: str, timestamp: str = None, parent=None):
        """
        role: 'user' | 'ai' | 'system'
        """
        super().__init__(parent)
        self.role = role
        self._text = text
        self._timestamp = timestamp or datetime.now().strftime('%H:%M')
        self._build()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 4, 16, 4)
        layout.setSpacing(10)

        # 角色标识符 — 几何符号替代 Emoji
        avatar = QLabel()
        avatar.setFixedSize(28, 28)
        avatar.setAlignment(Qt.AlignCenter)

        if self.role == 'user':
            avatar.setText('○')
            avatar.setStyleSheet(self._avatar_style(COLORS['accent']))
            layout.addStretch()
            layout.addWidget(self._build_bubble())
            layout.addWidget(avatar, alignment=Qt.AlignTop)
        elif self.role == 'ai':
            avatar.setText('◆')
            avatar.setStyleSheet(self._avatar_style(COLORS['safe']))
            layout.addWidget(avatar, alignment=Qt.AlignTop)
            layout.addWidget(self._build_bubble())
            layout.addStretch()
        else:  # system
            avatar.setText('◇')
            avatar.setFixedSize(20, 20)
            avatar.setStyleSheet(self._avatar_style(COLORS['text_muted'], 20))
            layout.addStretch(1)
            layout.addWidget(avatar, alignment=Qt.AlignTop)
            layout.addWidget(self._build_bubble())
            layout.addStretch(1)

    def _avatar_style(self, color: str, size: int = 28) -> str:
        return f"""
            QLabel {{
                background-color: {COLORS['bg_inset']};
                color: {color};
                border: none;
                border-radius: {size // 2}px;
                font-size: {size // 2 + 2}px;
                qproperty-alignment: AlignCenter;
            }}
        """

    def _build_bubble(self) -> QFrame:
        bubble = QFrame()
        bubble.setObjectName(f'bubble_{self.role}')

        b_layout = QVBoxLayout(bubble)
        b_layout.setContentsMargins(14, 10, 14, 10)
        b_layout.setSpacing(4)

        # 消息文本
        self._text_label = QLabel(self._text)
        self._text_label.setWordWrap(True)
        self._text_label.setTextFormat(Qt.PlainText)
        self._text_label.setMaximumWidth(400)
        self._text_label.setStyleSheet(self._text_style())
        self._text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        b_layout.addWidget(self._text_label)

        # 时间戳
        time_label = QLabel(self._timestamp)
        time_label.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 10px; letter-spacing: 0.5px;")
        alignment = Qt.AlignRight if self.role == 'user' else Qt.AlignLeft
        time_label.setAlignment(alignment)
        b_layout.addWidget(time_label)

        bubble.setStyleSheet(self._bubble_style())
        return bubble

    def _bubble_style(self) -> str:
        if self.role == 'user':
            bg = COLORS['user_bubble']
        elif self.role == 'ai':
            bg = COLORS['ai_bubble']
        else:
            bg = COLORS['system_bubble']

        return f"""
            QFrame#bubble_{self.role} {{
                background-color: {bg};
                border: none;
                border-radius: 8px;
            }}
        """

    def _text_style(self) -> str:
        color = COLORS['text_primary']
        size = '13px'
        if self.role == 'system':
            color = COLORS['text_secondary']
            size = '12px'
        return f"color: {color}; font-size: {size}; line-height: 1.6;"

    def update_text(self, new_text: str):
        """更新气泡文本 (用于流式输出)"""
        self._text = new_text
        if hasattr(self, '_text_label'):
            self._text_label.setText(new_text)

    @property
    def text(self) -> str:
        return self._text


# 快速操作按钮
class QuickActionBar(QFrame):
    """快速操作按钮栏"""

    action_clicked = pyqtSignal(str)

    ACTIONS = [
        ('快速扫描', 'scan', '扫描系统安全状态'),
        ('病毒检测', 'virus', '检查可疑进程和 Defender'),
        ('漏洞检查', 'vuln', '检查端口和防火墙'),
        ('安全报告', 'report', 'AI 生成安全分析报告'),
        ('修复建议', 'fix', '获取安全加固建议'),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('actionBar')

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(8)
        layout.addStretch()

        for label, action_id, tooltip in self.ACTIONS:
            btn = QPushButton(label)
            btn.setToolTip(tooltip)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(self._btn_style())
            btn.clicked.connect(lambda checked, a=action_id: self.action_clicked.emit(a))
            layout.addWidget(btn)

        layout.addStretch()

        self.setStyleSheet(f"""
            QFrame#actionBar {{
                background-color: {COLORS['bg_primary']};
                border-bottom: 1px solid {COLORS['border']};
            }}
        """)

    def _btn_style(self) -> str:
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {COLORS['text_secondary']};
                border: 1px solid {COLORS['border']};
                border-radius: 14px;
                padding: 5px 14px;
                font-size: 11px;
                letter-spacing: 1px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text_primary']};
                border-color: {COLORS['border_focus']};
            }}
        """


# 输入区域
class ChatInputBar(QFrame):
    """聊天输入框 + 发送按钮"""

    send_message = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('inputBar')
        self.setFixedHeight(64)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        # 文本输入框
        self._input = QTextEdit()
        self._input.setPlaceholderText('输入消息，或点击上方按钮快速操作...')
        self._input.setMaximumHeight(40)
        self._input.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text_primary']};
                border: none;
                border-radius: 8px;
                padding: 8px 14px;
                font-size: 13px;
                selection-background-color: {COLORS['accent_soft']};
            }}
            QTextEdit:focus {{
                background-color: {COLORS['bg_inset']};
            }}
        """)
        self._input.installEventFilter(self)
        layout.addWidget(self._input, stretch=1)

        # 发送按钮
        self._send_btn = QPushButton('发送')
        self._send_btn.setCursor(Qt.PointingHandCursor)
        self._send_btn.setFixedWidth(72)
        self._send_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['accent']};
                color: {COLORS['white']};
                border: none;
                border-radius: 8px;
                padding: 8px 14px;
                font-size: 12px;
                font-weight: 600;
                letter-spacing: 1px;
            }}
            QPushButton:hover {{
                background-color: #2563eb;
            }}
            QPushButton:disabled {{
                background-color: {COLORS['bg_card']};
                color: {COLORS['text_muted']};
            }}
        """)
        self._send_btn.clicked.connect(self._on_send)
        layout.addWidget(self._send_btn)

        self.setStyleSheet(f"""
            QFrame#inputBar {{
                background-color: {COLORS['bg_primary']};
                border-top: 1px solid {COLORS['border']};
            }}
        """)

    def _on_send(self):
        text = self._input.toPlainText().strip()
        if text:
            self.send_message.emit(text)
            self._input.clear()

    def eventFilter(self, obj, event):
        """Ctrl+Enter 发送消息"""
        from PyQt5.QtCore import QEvent as QtEvent
        if obj == self._input and event.type() == QtEvent.KeyPress:
            if event.key() == Qt.Key_Return and event.modifiers() == Qt.ControlModifier:
                self._on_send()
                return True
        return super().eventFilter(obj, event)

    def set_enabled(self, enabled: bool):
        self._input.setEnabled(enabled)
        self._send_btn.setEnabled(enabled)


# 聊天窗口主体
class ChatWindow(QDialog):
    """AI 安全管家对话窗口"""

    def __init__(self, controller, logger: logging.Logger = None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.logger = logger or logging.getLogger(__name__)
        self._conversation: List[Dict[str, str]] = []
        self._full_history: List[Dict[str, str]] = []
        self._streaming_bubble: Optional[ChatBubble] = None
        self._streaming_text = ""
        self._worker: Optional[LLMWorker] = None
        self._is_processing = False
        self._message_widgets: list = []

        # Knowledge base — 后台线程加载。
        # 默认向量库在进程内、嵌入是本地 HTTP 服务，都可在后台线程安全调用；
        # 服务不可达时 get_knowledge_base() 自动降级为关键词检索，绝不崩溃。
        self._kb = None
        self._kb_loaded = False
        if HAS_KB:
            self._ensure_kb()

        # Agent 核心（状态图）—— 也在后台加载：AgentCore.__init__ 里的
        # MCPManager 会连外部子进程，可能阻塞数秒。GUI 与 CLI 现在共用这一份
        # 实现，不再各写一套 ReAct 循环。
        self._agent = None
        self._agent_loaded = False
        self._agent_failed = False
        if HAS_AGENT:
            self._ensure_agent()

        self._build_ui()
        self._add_welcome_message()

        # 看门狗
        self._watchdog = QTimer(self)
        self._watchdog.timeout.connect(self._watchdog_check)
        self._watchdog.start(5000)

        # 流式输出节流 — 累积文本后每 ~60ms 刷新一次气泡。
        # 逐 token setText() 会触发全量重排版，把主线程拖死（表现为对话时卡死）。
        self._stream_flush_timer = QTimer(self)
        self._stream_flush_timer.setSingleShot(True)
        self._stream_flush_timer.setInterval(60)
        self._stream_flush_timer.timeout.connect(self._flush_streaming_text)

    # UI 构建
    def _build_ui(self):
        self.setWindowTitle('AI 安全对话')
        self.setMinimumSize(720, 600)
        self.resize(800, 680)
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS['bg_primary']}; }}")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 标题栏
        header = QFrame()
        header.setObjectName('chatHeader')
        header.setFixedHeight(52)
        header.setStyleSheet(f"""
            QFrame#chatHeader {{
                background-color: {COLORS['bg_primary']};
                border-bottom: 1px solid {COLORS['border']};
            }}
        """)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(20, 10, 20, 10)

        title = QLabel('AI 安全对话')
        title.setStyleSheet(
            f"color: {COLORS['text_primary']}; font-size: 15px; font-weight: 600; letter-spacing: 0.5px;")
        h_layout.addWidget(title)

        subtitle = QLabel('安小盾')
        subtitle.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; letter-spacing: 1px;")
        h_layout.addWidget(subtitle)
        h_layout.addSpacing(12)

        # 连接状态
        self._conn_dot = QLabel('●')
        self._conn_dot.setStyleSheet(
            f"color: {COLORS['safe']}; font-size: 7px;")
        h_layout.addWidget(self._conn_dot)

        try:
            llm = self.controller.llm
            available = llm.available_count if llm else 0
        except Exception:
            available = 0

        self._conn_label = QLabel(
            f'{"已连接" if available > 0 else "未配置"}')
        self._conn_label.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; letter-spacing: 1px;")
        h_layout.addWidget(self._conn_label)
        h_layout.addStretch()

        # 清空对话按钮
        clear_btn = QPushButton('清空')
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.setToolTip('清空对话历史')
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {COLORS['text_muted']};
                border: 1px solid {COLORS['border']};
                border-radius: 6px;
                padding: 5px 14px;
                font-size: 11px;
                letter-spacing: 1px;
            }}
            QPushButton:hover {{
                color: {COLORS['danger']};
                border-color: {COLORS['danger']};
            }}
        """)
        clear_btn.clicked.connect(self._clear_conversation)
        h_layout.addWidget(clear_btn)

        main_layout.addWidget(header)

        # 快速操作栏
        action_bar = QuickActionBar()
        action_bar.action_clicked.connect(self._on_quick_action)
        main_layout.addWidget(action_bar)

        # 消息列表区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: {COLORS['bg_primary']};
                border: none;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 6px;
                margin: 0;
            }}
            QScrollBar::handle:vertical {{
                background: {COLORS['border_focus']};
                border-radius: 3px;
                min-height: 40px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {COLORS['accent']};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
        """)

        self._msg_container = QWidget()
        self._msg_container.setObjectName('msgContainer')
        self._msg_container.setStyleSheet(
            f"QWidget#msgContainer {{ background-color: {COLORS['bg_primary']}; }}")
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setContentsMargins(12, 16, 12, 16)
        self._msg_layout.setSpacing(10)
        self._msg_layout.addStretch()

        scroll_area.setWidget(self._msg_container)

        self._scroll_area = scroll_area
        QTimer.singleShot(100, self._scroll_to_bottom)

        main_layout.addWidget(scroll_area, stretch=1)

        # 输入栏
        self._input_bar = ChatInputBar()
        self._input_bar.send_message.connect(self._on_user_message)
        main_layout.addWidget(self._input_bar)

    # 欢迎消息
    def _add_welcome_message(self):
        try:
            llm_available = self.controller.llm.available_count > 0
        except Exception:
            llm_available = False

        if llm_available:
            welcome = (
                "你好，我是安小盾，你的 AI 网络安全管家 🛡️\n\n"
                "我可以直接调用系统安全工具:\n"
                "  🔍 扫描进程 — 检测恶意软件\n"
                "  🌐 分析网络 — 发现可疑连接\n"
                "  🔒 检查防火墙 — 验证防护状态\n"
                "  📊 系统诊断 — CPU/内存/端口\n"
                "  🕵️ 威胁情报 — IP/域名信誉查询\n\n"
                "直接跟我说话，我会主动使用工具帮你分析！"
            )
        else:
            welcome = (
                "你好，我是安小盾，你的 AI 网络安全管家\n\n"
                "⚠️ AI 模型未配置，智能对话不可用。\n"
                "快速操作按钮仍可使用本地安全扫描。\n\n"
                "配置 DeepSeek 以获得 AI 智能分析:\n"
                "  1. 访问 https://platform.deepseek.com\n"
                "  2. 获取 API Key\n"
                "  3. 在 config.yaml 填入 api_key\n"
                "  4. 重启程序"
            )

        self._add_message(welcome, 'ai')

    # 消息管理
    def _add_message(self, text: str, role: str) -> ChatBubble:
        """添加消息到聊天区域"""
        if self._msg_layout.count() > 0:
            last_item = self._msg_layout.itemAt(self._msg_layout.count() - 1)
            if last_item.spacerItem():
                self._msg_layout.removeItem(last_item)

        bubble = ChatBubble(text, role)
        self._msg_layout.addWidget(bubble)
        self._msg_layout.addStretch()
        self._message_widgets.append(bubble)

        if role in ('user', 'ai'):
            # LLM API 要求 role 为 'user'/'assistant'，内部用 'ai' 需转换
            api_role = 'assistant' if role == 'ai' else 'user'
            self._conversation.append({"role": api_role, "content": text})
            # Track full history for KB save (untruncated)
            self._full_history.append({"role": api_role, "content": text})

        QTimer.singleShot(50, self._scroll_to_bottom)

        return bubble

    def _scroll_to_bottom(self):
        scrollbar = self._scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _clear_conversation(self):
        # Save current conversation to KB before clearing
        self._save_to_kb()

        while self._msg_layout.count() > 0:
            item = self._msg_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._conversation.clear()
        self._full_history.clear()
        self._message_widgets.clear()
        self._msg_layout.addStretch()
        self._add_welcome_message()

    def _save_to_kb(self):
        """保存当前对话到知识库（需用户确认）。"""
        self._ensure_kb()
        if not self._kb or not self._full_history:
            return
        # Filter out system messages and the welcome message
        savable = [m for m in self._full_history
                   if m.get("role") in ("user", "assistant")]
        if len(savable) < 2:  # At least one Q&A pair
            return

        # 询问用户是否保存
        reply = QMessageBox.question(
            self, '保存对话到知识库',
            '是否将当前对话保存到知识库？\n\n'
            '保存后，AI 可以在未来的对话中参考这些内容，\n'
            '让你的安全管家越用越聪明。',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            conv_id = self._kb.add_conversation(savable)
            if conv_id:
                self.logger.info(f"对话已保存到知识库: {conv_id}")
        except Exception as e:
            self.logger.debug(f"保存对话失败: {e}")

    # 用户输入处理
    def _on_user_message(self, text: str):
        if self._is_processing:
            return

        self._add_message(text, 'user')
        self._is_processing = True
        self._input_bar.set_enabled(False)
        self._call_ai(text)

    # KB 延迟加载（后台线程，网络客户端线程安全）
    def _ensure_kb(self):
        """延迟加载知识库，避免阻塞 UI 线程。"""
        if self._kb is not None or self._kb_loaded:
            return
        self._kb_loaded = True  # 防止重复启动
        threading.Thread(target=self._kb_load_worker, daemon=True).start()

    def _kb_load_worker(self):
        """后台加载 KB：嵌入服务探测 + 向量库探活，均带短超时。

        服务不可达时 get_knowledge_base() 自动降级（关键词检索），
        绝不让 GUI 卡住或崩溃。
        """
        try:
            from agent.config import AgentConfig
            from agent.knowledge_base import get_knowledge_base

            cfg = AgentConfig.from_config_file(str(Path(__file__).parent / "config.yaml"))
            kb = get_knowledge_base(
                persist_dir=cfg.knowledge_base_dir or None,
                vector_db_cfg=cfg.knowledge_base_vector_db,
                embedding_cfg=cfg.knowledge_base_embedding,
            )
            self._kb = kb  # GIL 原子赋值
            self.logger.info(
                f"知识库已加载: {kb.conversation_count} 对话, {kb.count} 向量, "
                f"嵌入={kb._embed_type}, 向量库={kb._vector_db_name}")
        except Exception as e:
            self.logger.debug(f"知识库加载失败: {e}")
            self._kb = None

    # Agent 核心延迟初始化
    def _ensure_agent(self):
        """后台构建 AgentCore（状态图 + 工具 + 技能）。"""
        if self._agent is not None or self._agent_loaded:
            return
        self._agent_loaded = True
        threading.Thread(target=self._agent_load_worker, daemon=True).start()

    def _agent_load_worker(self):
        try:
            from agent.config import AgentConfig
            from agent.core import AgentCore

            cfg = AgentConfig.from_config_file(str(Path(__file__).parent / "config.yaml"))
            # 保留 GUI 的人格提示词与迭代预算
            cfg.system_prompt = SECURITY_AGENT_PROMPT
            cfg.max_iterations = LLMWorker.MAX_TOOL_ITERATIONS
            # 人在场：审批走 approval_request 信号 + QMessageBox，
            # 因此显式 interactive，不做「无 tty 就降级为拒绝」那套（那是 CLI 的）
            cfg.approval_mode = "interactive"

            self._agent = AgentCore(cfg, knowledge_base=self._kb)
            self.logger.info(
                f"Agent 核心已加载: {self._agent.tool_count} 工具, "
                f"{self._agent.skill_count} 技能")
        except Exception as e:
            self.logger.debug(f"Agent 核心加载失败: {e}")
            self._agent = None
            self._agent_failed = True

    # AI 调用（驱动状态图）
    def _call_ai(self, user_message: str):
        if self._agent is None:
            self._add_message(
                "AI 核心初始化失败。请检查 agent/ 模块与 config.yaml。" if self._agent_failed
                else "AI 核心仍在初始化（首次启动要加载工具与 MCP），请稍候再试。",
                'system')
            self._on_ai_response("", False)
            return

        # UI 占位气泡 (不加入对话历史)
        self._streaming_bubble = self._add_message('思考中...', 'ai')
        self._streaming_text = ""

        self._worker = LLMWorker(self._agent, message=user_message, parent=self)
        self._worker.streaming.connect(self._on_stream_chunk)
        self._worker.tool_call_signal.connect(self._on_tool_call)
        self._worker.tool_result_signal.connect(self._on_tool_result)
        self._worker.approval_request.connect(self._on_approval_request)
        self._worker.finished.connect(self._on_ai_response)
        self._worker.start()

    def _run_agent_task(self, prompt: str, bubble: ChatBubble, on_done):
        """跑一次一次性 agent 任务（安全报告 / 修复建议）。

        用 ephemeral=True 走独立 thread —— 这些系统指令不该写进用户的对话历史。
        """
        if self._agent is None:
            self._update_bubble_text(bubble, "AI 核心尚未就绪，请稍后再试。")
            return

        self._is_processing = True
        self._input_bar.set_enabled(False)

        worker = LLMWorker(self._agent, message=prompt, parent=self, ephemeral=True)
        buffer: list = []

        def _on_chunk(chunk: str):
            buffer.append(chunk)
            self._update_bubble_text(bubble, "".join(buffer))

        worker.streaming.connect(_on_chunk)
        worker.approval_request.connect(self._on_approval_request)
        worker.finished.connect(lambda text, ok: on_done(text, ok, bubble))
        # 赋给 self._worker：审批握手与看门狗都认这一个
        self._worker = worker
        worker.start()

    def _on_approval_request(self, request_id: str, payload: dict):
        """主线程：弹确认对话框，并把结果交回 worker。"""
        worker = self._worker
        if worker is None:
            return

        # 关键：QMessageBox 是模态的，其内嵌事件循环会**继续处理 QTimer**。
        # 不暂停看门狗的话，用户还在读对话框时线程就可能被判超时。
        self._watchdog.stop()
        try:
            tool = payload.get("tool", "?")
            risk = payload.get("risk_level", "unknown")
            args = json.dumps(payload.get("arguments") or {}, ensure_ascii=False)
            if len(args) > 400:
                args = args[:400] + "…"

            reply = QMessageBox.question(
                self, '安全操作确认',
                f"AI 请求执行高风险操作\n\n"
                f"工具: {tool}\n"
                f"风险等级: {risk}\n"
                f"参数: {args}\n\n"
                f"是否允许执行？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No)   # 默认 No —— 与 fail-closed 的口径一致

            approved = reply == QMessageBox.Yes
            worker.deliver_approval(request_id, {
                "approved": approved,
                "reason": "gui_user" if approved else "gui_denied",
            })
        finally:
            worker.note_progress()
            self._watchdog.start()

    def _on_stream_chunk(self, chunk: str):
        self._streaming_text += chunk
        if self._streaming_bubble and not self._stream_flush_timer.isActive():
            # 只累积文本，重排版/滚动交给定时器批量执行（~16Hz）
            self._stream_flush_timer.start()

    def _flush_streaming_text(self):
        """定时批量刷新流式气泡文本（节流后的实际渲染点）。"""
        if self._streaming_bubble:
            self._update_bubble_text(self._streaming_bubble, self._streaming_text)
            self._scroll_to_bottom()

    def _on_tool_call(self, tool_name: str, args_summary: str):
        """显示工具调用"""
        icon = {'scan_network': '🌐', 'scan_processes': '🔍', 'check_firewall': '🔒',
                'get_system_state': '📊', 'security_summary': '🛡️',
                'read_security_logs': '📋', 'get_listening_ports': '🔌',
                'run_command': '⚡', 'threat_check_ip': '🕵️',
                'threat_check_domain': '🌍', 'cve_search': '📚', 'cve_lookup': '🔎',
                'web_search': '🔍', 'defender_status': '🛡️'}.get(tool_name, '🔧')
        self._add_message(f'{icon} 调用工具: {tool_name}', 'system')

    def _on_tool_result(self, tool_name: str, result_summary: str):
        """显示工具结果摘要 (截断)"""
        brief = result_summary[:200] + ('...' if len(result_summary) > 200 else '')
        self._add_message(f'✅ {tool_name}: {brief}', 'system')

    def _update_bubble_text(self, bubble: ChatBubble, new_text: str):
        if hasattr(bubble, '_text_label'):
            bubble._text_label.setText(new_text)
            bubble._text = new_text

    def _on_ai_response(self, response_text: str, success: bool):
        # 停掉节流定时器，用最终文本收尾
        self._stream_flush_timer.stop()

        # 更新占位气泡
        if self._streaming_bubble:
            self._update_bubble_text(self._streaming_bubble, response_text)

        # 添加到对话历史 (仅成功且非空的回复)
        if success and response_text.strip():
            self._conversation.append(
                {"role": "assistant", "content": response_text})
            self._full_history.append(
                {"role": "assistant", "content": response_text})

        self._streaming_bubble = None
        self._streaming_text = ""
        self._worker = None

        self._is_processing = False
        self._input_bar.set_enabled(True)
        self._scroll_to_bottom()

    # 快速操作
    def _on_quick_action(self, action_id: str):
        if self._is_processing:
            return

        action_handlers = {
            'scan': self._do_quick_scan,
            'virus': self._do_virus_check,
            'vuln': self._do_vuln_check,
            'report': self._do_security_report,
            'fix': self._do_fix_advice,
        }

        handler = action_handlers.get(action_id)
        if handler:
            handler()

    def _do_quick_scan(self):
        """快速扫描系统安全状态"""
        self._add_message('正在执行快速安全扫描...', 'system')
        self._is_processing = True
        self._input_bar.set_enabled(False)

        try:
            state = self.controller.get_state()

            lines = []
            lines.append(f"快速扫描报告 — {datetime.now().strftime('%H:%M:%S')}")
            lines.append("─" * 36)

            sec_level = state.get('sec_level', 'safe')
            lines.append(f"安全等级: {sec_level.upper()}")

            fw = state.get('firewall_on', True)
            lines.append(f"防火墙: {'开启' if fw else '关闭'}")

            av = state.get('defender_on', True)
            lines.append(f"防病毒: {'运行中' if av else '未运行'}")

            threats = state.get('threat_count', 0)
            lines.append(f"活跃威胁: {threats} 个")

            suspicious = state.get('suspicious_ips', 0)
            conns = state.get('active_connections', 0)
            lines.append(f"活跃连接: {conns} | 可疑IP: {suspicious}")

            cpu = state.get('cpu_usage', 0)
            mem = state.get('mem_usage', 0)
            lines.append(f"CPU: {cpu:.1f}% | 内存: {mem:.1f}%")

            msgs = state.get('messages', [])
            if msgs:
                lines.append("\n最近事件:")
                for m in msgs[-3:]:
                    lines.append(f"  > {m}")

            if sec_level == 'safe' and fw and av:
                lines.append("\n总体评价: 系统状态良好，未发现明显威胁。")
            elif sec_level == 'danger':
                lines.append("\n总体评价: 发现严重威胁，建议立即处理！")
            else:
                lines.append("\n总体评价: 存在一些值得注意的问题，建议进一步检查。")

            scan_result = '\n'.join(lines)
            self._add_message(scan_result, 'system')

        except Exception as e:
            self._add_message(f'扫描失败: {e}', 'system')

        self._is_processing = False
        self._input_bar.set_enabled(True)

    def _do_virus_check(self):
        """病毒检测：扫描可疑进程 + Defender 状态"""
        self._add_message('正在执行病毒检测...', 'system')
        self._is_processing = True
        self._input_bar.set_enabled(False)

        try:
            lines = [f"病毒检测报告 — {datetime.now().strftime('%H:%M:%S')}"]
            lines.append("─" * 36)

            try:
                fw_result = self.controller.firewall.check()
                defender_on = fw_result.get('defender_on', True)
                defender_details = fw_result.get('defender_details', {})

                lines.append(f"Windows Defender: {'运行中' if defender_on else '未运行'}")

                if defender_details:
                    rtp = defender_details.get('RealTimeProtectionEnabled', False)
                    behavior = defender_details.get('BehaviorMonitorEnabled', False)
                    antispy = defender_details.get('AntispywareEnabled', False)
                    lines.append(f"  实时保护: {'开启' if rtp else '关闭'}")
                    lines.append(f"  行为监控: {'开启' if behavior else '关闭'}")
                    lines.append(f"  反间谍: {'开启' if antispy else '关闭'}")
            except Exception:
                lines.append('Windows Defender 状态检查不可用')

            try:
                proc_result = self.controller.process.scan()
                suspicious_count = proc_result.get('suspicious_count', 0)
                suspicious_details = proc_result.get('suspicious_details', [])

                lines.append(f"\n可疑进程: {suspicious_count} 个")
                if suspicious_details:
                    for detail in suspicious_details[:5]:
                        pid = detail.get('pid', '?')
                        name = detail.get('name', '?')
                        reason = detail.get('reason', '')
                        lines.append(f"  PID:{pid} {name} — {reason}")

                high_cpu = proc_result.get('high_cpu_details', [])
                if high_cpu:
                    lines.append(f"\n高CPU进程 (>{self.controller.process.cpu_threshold}%):")
                    for p in high_cpu[:3]:
                        lines.append(f"  PID:{p['pid']} {p['name']} CPU:{p['cpu']}")
            except Exception as e:
                lines.append(f"进程扫描失败: {e}")

            if not defender_on:
                lines.append("\n建议: 立即开启 Windows Defender 实时保护！")
            elif suspicious_count > 0:
                lines.append(f"\n建议: 发现 {suspicious_count} 个可疑进程，建议进一步调查。")

            self._add_message('\n'.join(lines), 'system')

        except Exception as e:
            self._add_message(f'病毒检测失败: {e}', 'system')

        self._is_processing = False
        self._input_bar.set_enabled(True)

    def _do_vuln_check(self):
        """漏洞检查：端口扫描 + 防火墙配置"""
        self._add_message('正在执行漏洞检查...', 'system')
        self._is_processing = True
        self._input_bar.set_enabled(False)

        try:
            lines = [f"漏洞检查报告 — {datetime.now().strftime('%H:%M:%S')}"]
            lines.append("─" * 36)

            try:
                fw_result = self.controller.firewall.check()
                firewall_on = fw_result.get('firewall_on', True)
                profiles = fw_result.get('firewall_profiles', {})

                lines.append(f"Windows 防火墙: {'开启' if firewall_on else '关闭'}")
                if profiles:
                    for profile, enabled in profiles.items():
                        lines.append(f"  {profile}: {'开启' if enabled else '关闭'}")
                if not firewall_on:
                    lines.append("  防火墙关闭意味着所有端口直接暴露在网络上！")
            except Exception as e:
                lines.append(f"防火墙检查失败: {e}")

            try:
                listen_ports = self.controller.network.get_listening_ports()
                lines.append(f"\n监听端口: {len(listen_ports)} 个")
                standard_ports = {80, 443, 22, 3389, 135, 139, 445, 5040, 8080, 8443}
                unusual_ports = [p for p in listen_ports if p not in standard_ports]
                if unusual_ports:
                    lines.append(f"非标准监听端口: {', '.join(map(str, unusual_ports[:10]))}")
                if len(listen_ports) > 20:
                    lines.append(f"开放端口较多 ({len(listen_ports)} 个)，建议审查不必要的服务")
            except Exception as e:
                lines.append(f"端口扫描失败: {e}")

            try:
                state = self.controller.get_state()
                active_conns = state.get('active_connections', 0)
                suspicious_ips = state.get('suspicious_ips', 0)

                lines.append(f"\n网络连接: {active_conns} 个活跃连接")
                if suspicious_ips > 0:
                    lines.append(f"发现 {suspicious_ips} 个可疑 IP 连接")
            except Exception:
                pass

            lines.append("\n加固建议:")
            if not firewall_on:
                lines.append("  1. 立即开启 Windows 防火墙")
            if unusual_ports and len(unusual_ports) > 5:
                lines.append("  2. 审查非标准端口，关闭不必要的服务")
            lines.append("  3. 确保系统已安装最新安全更新")
            lines.append("  4. 定期检查防火墙入站规则")

            self._add_message('\n'.join(lines), 'system')

        except Exception as e:
            self._add_message(f'漏洞检查失败: {e}', 'system')

        self._is_processing = False
        self._input_bar.set_enabled(True)

    def _do_security_report(self):
        """AI 生成安全分析报告 (使用工具获取实时数据)"""
        state = self.controller.get_state()
        sec_level = state.get('sec_level', 'safe')
        threats = state.get('threat_count', 0)
        cpu = state.get('cpu_usage', 0)
        mem = state.get('mem_usage', 0)
        fw = state.get('firewall_on', True)
        av = state.get('defender_on', True)

        summary = (
            f'安全状态: {sec_level.upper()} | '
            f'威胁: {threats} | CPU: {cpu:.1f}% | 内存: {mem:.1f}%\n'
            f'防火墙: {"开启" if fw else "关闭"} | '
            f'Defender: {"开启" if av else "关闭"}'
        )
        self._add_message(summary, 'system')

        if self._agent and self._agent.llm.available_count > 0:
            prompt = (
                "请调用安全工具获取实时数据，然后生成一份简洁的安全分析报告（100字以内）:\n"
                "先调用 scan_network + check_firewall + get_system_state，"
                "然后根据结果给出: 1)总体评价 2)主要风险 3)优先处理事项"
            )
            analysis_bubble = self._add_message('AI 分析中...', 'ai')
            self._run_agent_task(prompt, analysis_bubble, self._on_report_done)
        else:
            self._add_message(
                '配置 AI 模型后可获得智能安全分析报告。', 'system')

    def _on_report_done(self, text: str, success: bool, bubble: ChatBubble):
        if success:
            self._update_bubble_text(bubble, text)
        else:
            self._update_bubble_text(bubble, f'分析失败: {text}')
        self._is_processing = False
        self._input_bar.set_enabled(True)

    def _do_fix_advice(self):
        """获取安全修复建议 (使用工具分析)"""
        state = self.controller.get_state()
        issues = []
        if not state.get('firewall_on', True):
            issues.append('防火墙已关闭')
        if not state.get('defender_on', True):
            issues.append('Windows Defender 未运行')
        if state.get('threat_count', 0) > 0:
            issues.append(f"发现 {state.get('threat_count')} 个活跃威胁")
        if state.get('suspicious_ips', 0) > 0:
            issues.append(f"发现 {state.get('suspicious_ips')} 个可疑 IP 连接")
        if state.get('cpu_usage', 0) > 80:
            issues.append(f"CPU 使用率过高 ({state.get('cpu_usage', 0):.0f}%)")

        if not issues:
            self._add_message(
                '当前系统状态良好，未发现需要修复的问题。\n\n'
                '日常安全建议:\n'
                '  保持 Windows 和软件更新\n'
                '  定期运行 Windows Defender 全盘扫描\n'
                '  谨慎下载和运行未知来源的程序\n'
                '  定期备份重要数据',
                'system')
            return

        issues_text = '\n'.join(f'  - {i}' for i in issues)
        self._add_message(f'发现以下问题:\n{issues_text}', 'system')

        if self._agent and self._agent.llm.available_count > 0:
            prompt = (
                f"用户的系统存在以下安全问题:\n{issues_text}\n\n"
                f"先调用相关工具确认问题严重性，然后给出具体可操作的修复建议。"
            )
            fix_bubble = self._add_message('生成修复方案中...', 'ai')
            self._run_agent_task(prompt, fix_bubble, self._on_report_done)
        else:
            fix_lines = ['修复建议:']
            if not state.get('firewall_on', True):
                fix_lines.append('\n开启防火墙: 设置 -> 安全中心 -> 防火墙')
            if not state.get('defender_on', True):
                fix_lines.append('\n开启 Defender: 安全中心 -> 病毒防护')
            self._add_message('\n'.join(fix_lines), 'ai')

    # 看门狗
    def _watchdog_check(self):
        """防止 _is_processing 永久卡死。

        语义已从「总时长超时」改成「**无进展**超时」—— 每收到一个事件就重置计时。
        并且优先**协作取消**而不是 terminate()：QThread.terminate() 在 Windows 上是
        TerminateThread，会在任意字节码边界撕断线程；如果那一刻正在写 SQLite
        checkpoint，就会留下半写状态。

        好在架构上本来就安全：图只在 approval 节点中断，那是个干净的 checkpoint
        边界，tools 节点尚未开始，所以不存在「工具执行到一半」的持久化状态。
        """
        if not (self._is_processing and self._worker):
            return
        if self._worker.waiting_for_approval:
            return   # 人还没点，不算卡死
        if self._worker.seconds_since_progress > 35:
            self.logger.warning(
                f"LLM Worker 无进展 {self._worker.seconds_since_progress:.0f}s，请求取消")
            self._worker.request_cancel()
            if not self._worker.wait(3000):
                self.logger.warning("协作取消失败，强制终止线程")
                self._worker.terminate()
            self._on_ai_response("AI 响应超时，请稍后重试。", False)

    # 窗口事件
    def closeEvent(self, event):
        self._watchdog.stop()
        self._save_to_kb()
        if self._worker and self._worker.isRunning():
            self._worker.request_cancel()
            if not self._worker.wait(3000):
                self._worker.terminate()
        super().closeEvent(event)


# 独立测试
if __name__ == '__main__':
    import random

    class MockController:
        def get_state(self):
            sec = random.choices(['safe', 'warning', 'danger'], weights=[0.7, 0.2, 0.1])[0]
            return {
                'sec_level': sec,
                'threat_count': random.randint(0, 3),
                'blocked_count': 0,
                'active_connections': random.randint(3, 30),
                'suspicious_ips': random.randint(0, 2),
                'net_status': 'normal',
                'firewall_on': random.choice([True, True, True, False]),
                'defender_on': random.choice([True, True, True, False]),
                'cpu_usage': random.uniform(5, 85),
                'mem_usage': random.uniform(25, 80),
                'uptime': 3600,
                'messages': ['检测到可疑连接: 192.168.1.100:4444'] if sec != 'safe' else [],
                'ai_status': 'idle',
                'ai_task': '',
                'ai_progress': 0,
            }
        def stop(self): pass

    class MockLLM:
        available_count = 0
        _router = None

    class MockProc:
        cpu_threshold = 80
        def scan(self):
            return {'suspicious_count': 0, 'suspicious_names': [],
                    'suspicious_details': [], 'high_cpu_details': []}

    class MockNet:
        def get_listening_ports(self):
            return [80, 443, 3389, 8080, 55555]

    class MockFW:
        def check(self):
            return {'firewall_on': True, 'defender_on': True,
                    'firewall_profiles': {'Domain': True, 'Private': True, 'Public': True},
                    'defender_details': {'RealTimeProtectionEnabled': True,
                                         'BehaviorMonitorEnabled': True,
                                         'AntispywareEnabled': True}}

    mc = MockController()
    mc.llm = MockLLM()
    mc.process = MockProc()
    mc.network = MockNet()
    mc.firewall = MockFW()

    app = QApplication(sys.argv)
    chat = ChatWindow(mc)
    chat.show()
    app.exec_()

