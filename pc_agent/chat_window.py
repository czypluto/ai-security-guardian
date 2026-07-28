"""
============================================================
 AI 安全对话窗口 - Chat Window
 极简清爽风格 · 与 desktop_gui 统一设计语言
============================================================

功能:
  - 自由对话: 与 AI 安全管家"安小盾"交流
  - 快速操作: 一键扫描病毒/检查漏洞/安全分析
  - 实时扫描: 调用安全模块获取实时数据
  - 流式输出: LLM 回复逐字显示
  - 对话历史: 保持上下文连贯性
"""

import sys
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List

try:
    from PyQt5.QtWidgets import (
        QApplication, QDialog, QWidget, QFrame, QLabel,
        QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit,
        QScrollArea, QSizePolicy, QSplitter, QSpacerItem,
        QMessageBox,
    )
    from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QPropertyAnimation
    from PyQt5.QtGui import (
        QFont, QColor, QIcon, QPixmap, QPainter, QPen, QBrush,
        QTextCursor, QPalette, QFontMetrics,
    )
    HAS_PYQT5 = True
except ImportError:
    HAS_PYQT5 = False
    # Stub base classes to prevent NameError when module is imported without PyQt5
    QApplication = QDialog = QWidget = QFrame = QLabel = object
    QVBoxLayout = QHBoxLayout = QPushButton = QTextEdit = object
    QScrollArea = QSizePolicy = QSplitter = QSpacerItem = object
    QThread = pyqtSignal = object
    QTimer = QPropertyAnimation = object
    QFont = QColor = QIcon = QPixmap = QPainter = QPen = QBrush = object
    QTextCursor = QPalette = QFontMetrics = object
    Qt = type('Qt', (), {})()

# Knowledge base integration
try:
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from agent.knowledge_base import get_knowledge_base
    HAS_KB = True
except ImportError:
    HAS_KB = False


# ============================================================
# 颜色常量 — 与 desktop_gui 保持一致的极简清爽调色板
# ============================================================
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


# ============================================================
# AI 安全管家系统提示词
# ============================================================
SECURITY_AGENT_PROMPT = """你是一个名叫"安小盾"的 AI 网络安全管家。你运行在用户的 Windows PC 上，作为安全守护程序的一部分。

## 你的身份
- 名字: 安小盾
- 性格: 认真负责、专业可靠、又有点可爱的二次元风格安全专家
- 特长: 网络安全分析、病毒检测、漏洞扫描、系统安全加固

## 你的能力
1. **病毒检测**: 分析可疑进程、检查 Windows Defender 状态、识别恶意软件行为
2. **漏洞扫描**: 检查开放端口、防火墙配置、系统更新状态
3. **网络监控**: 分析网络连接、检测可疑 IP、识别 C2 通信
4. **安全建议**: 提供具体可操作的修复方案

## 回复规则
- 使用中文回复
- 保持专业但不失亲切，可以偶尔使用颜文字
- 如果用户报告安全问题，先安抚情绪再给出专业建议
- 对于不确定的内容，建议用户进行更深入的检查
- 回复长度适中，不要过长（一般不超过150字）
- 涉及具体操作步骤时，给出清晰明确指令
- 如果检测到严重威胁，语气要严肃但不要制造恐慌

## 当前上下文
你是桌面安全软件的一部分，可以直接访问系统的安全监控数据。
用户通过聊天窗口与你交流。你可以帮助用户理解安全威胁并解决问题。"""


# ============================================================
# LLM 后台工作线程
# ============================================================
class LLMWorker(QThread):
    """后台线程执行 LLM 调用，避免阻塞 UI。30秒超时自动终止。"""
    finished = pyqtSignal(str, bool)  # (response_text, success)
    streaming = pyqtSignal(str)       # 流式增量文本

    def __init__(self, llm_client, messages: list, parent=None):
        super().__init__(parent)
        self.llm = llm_client
        self.messages = messages
        self._start_time = 0

    def run(self):
        import time
        self._start_time = time.time()

        if self.llm is None or self.llm.available_count == 0:
            self.finished.emit(
                "未配置 AI 模型。请先在 config.yaml 中配置 LLM API Key。\n\n"
                "推荐免费方案:\n"
                "  智谱 glm-4-flash (免费): https://open.bigmodel.cn\n"
                "  硅基流动 (新用户免费): https://cloud.siliconflow.cn",
                False)
            return

        full_text = ""
        try:
            for chunk in self.llm.chat_stream(
                messages=self.messages,
                system_prompt=SECURITY_AGENT_PROMPT,
                max_tokens=512,
            ):
                # 15秒无数据则超时
                if time.time() - self._start_time > 30:
                    if full_text.strip():
                        break
                    else:
                        self.finished.emit("AI 响应超时，请稍后重试。", False)
                        return

                if chunk and not chunk.startswith('['):
                    full_text += chunk
                    self.streaming.emit(chunk)

            if full_text.strip():
                self.finished.emit(full_text.strip(), True)
            else:
                # 流式无输出，尝试非流式
                try:
                    response = self.llm.chat(
                        messages=self.messages,
                        system_prompt=SECURITY_AGENT_PROMPT,
                        max_tokens=512,
                    )
                    if response.success:
                        self.finished.emit(response.text, True)
                    else:
                        self.finished.emit(
                            f"AI 暂时无法响应: {response.error}\n请检查网络和 API 配置。", False)
                except Exception as e:
                    self.finished.emit(f"AI 调用失败: {str(e)}", False)
        except Exception as e:
            self.finished.emit(f"AI 调用异常: {str(e)}", False)


# ============================================================
# 消息气泡组件 — 极简风格
# ============================================================
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


# ============================================================
# 快速操作按钮 — 极简药丸样式
# ============================================================
class QuickActionBar(QFrame):
    """快速操作按钮栏 — 扁平极简"""

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


# ============================================================
# 输入区域 — 极简
# ============================================================
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


# ============================================================
# 聊天窗口主体 — 极简清爽版
# ============================================================
class ChatWindow(QDialog):
    """AI 安全管家对话窗口"""

    def __init__(self, controller, logger: logging.Logger = None, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.logger = logger or logging.getLogger(__name__)
        self._conversation: List[Dict[str, str]] = []
        self._full_history: List[Dict[str, str]] = []  # Complete history for KB save
        self._streaming_bubble: Optional[ChatBubble] = None
        self._streaming_text = ""
        self._worker: Optional[LLMWorker] = None
        self._is_processing = False
        self._message_widgets: list = []

        # Knowledge base (延迟加载，避免阻塞 UI)
        self._kb = None
        self._kb_loaded = False

        self._build_ui()
        self._add_welcome_message()

        # 看门狗：30秒强制重置 _is_processing，防止卡死
        self._watchdog = QTimer(self)
        self._watchdog.timeout.connect(self._watchdog_check)
        self._watchdog.start(5000)

    # ---- UI 构建 ----
    def _build_ui(self):
        self.setWindowTitle('AI 安全对话')
        self.setMinimumSize(720, 600)
        self.resize(800, 680)
        self.setStyleSheet(f"QDialog {{ background-color: {COLORS['bg_primary']}; }}")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ---- 标题栏 ----
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

        # ---- 快速操作栏 ----
        action_bar = QuickActionBar()
        action_bar.action_clicked.connect(self._on_quick_action)
        main_layout.addWidget(action_bar)

        # ---- 消息列表区域 ----
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

        # ---- 输入栏 ----
        self._input_bar = ChatInputBar()
        self._input_bar.send_message.connect(self._on_user_message)
        main_layout.addWidget(self._input_bar)

    # ---- 欢迎消息 ----
    def _add_welcome_message(self):
        try:
            llm_available = self.controller.llm.available_count > 0
        except Exception:
            llm_available = False

        if llm_available:
            welcome = (
                "你好，我是安小盾，你的 AI 网络安全管家\n\n"
                "我可以帮你:\n"
                "  快速扫描 - 检查系统安全状态\n"
                "  病毒检测 - 扫描可疑进程和恶意软件\n"
                "  漏洞检查 - 检查端口开放和防火墙配置\n"
                "  安全报告 - 生成完整的安全分析报告\n"
                "  修复建议 - 提供安全加固方案\n\n"
                "直接跟我说话，或者点击上方按钮开始吧"
            )
        else:
            welcome = (
                "你好，我是安小盾，你的 AI 网络安全管家\n\n"
                "AI 模型未配置，对话功能暂时不可用。\n"
                "快速操作（扫描/检测等）仍然可用。\n\n"
                "配置 AI 模型以获得智能对话体验:\n"
                "  1. 编辑 config.yaml\n"
                "  2. 填入 LLM API Key（推荐智谱免费模型）\n"
                "  3. 重启程序\n\n"
                "点击上方按钮执行安全操作"
            )

        self._add_message(welcome, 'ai')

    # ---- 消息管理 ----
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
        """Save current conversation to knowledge base (with user confirmation)."""
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

    # ---- 用户输入处理 ----
    def _on_user_message(self, text: str):
        if self._is_processing:
            return

        self._add_message(text, 'user')
        self._is_processing = True
        self._input_bar.set_enabled(False)
        self._call_ai(text)

    # ---- KB 延迟加载 ----
    def _ensure_kb(self):
        """延迟加载知识库，避免阻塞 UI 线程"""
        if self._kb_loaded or not HAS_KB:
            return
        self._kb_loaded = True
        try:
            self._kb = get_knowledge_base()
            self.logger.info(f"知识库已加载: {self._kb.conversation_count} 对话")
        except Exception as e:
            self.logger.debug(f"知识库初始化跳过: {e}")

    # ---- AI 调用 ----
    def _call_ai(self, user_message: str):
        try:
            llm = self.controller.llm
        except Exception:
            llm = None

        self._streaming_bubble = self._add_message('思考中...', 'ai')
        self._streaming_text = ""

        recent_messages = self._conversation[-20:]

        # Search knowledge base for relevant context (延迟加载)
        self._ensure_kb()
        kb_context = ""
        if self._kb:
            try:
                kb_context = self._kb.build_context(user_message, top_k=3)
                if kb_context:
                    self.logger.debug(f"KB: 检索到相关知识 ({len(kb_context)} 字符)")
            except Exception as e:
                self.logger.debug(f"KB 检索跳过: {e}")

        # Inject KB context as a system message before the recent messages
        if kb_context:
            kb_msg = {"role": "system", "content": kb_context}
            messages_for_llm = [kb_msg] + list(recent_messages)
        else:
            messages_for_llm = list(recent_messages)

        self._worker = LLMWorker(llm, messages_for_llm, self)
        self._worker.streaming.connect(self._on_stream_chunk)
        self._worker.finished.connect(self._on_ai_response)
        self._worker.start()

    def _on_stream_chunk(self, chunk: str):
        self._streaming_text += chunk
        if self._streaming_bubble:
            self._update_bubble_text(self._streaming_bubble, self._streaming_text)
            self._scroll_to_bottom()

    def _update_bubble_text(self, bubble: ChatBubble, new_text: str):
        if hasattr(bubble, '_text_label'):
            bubble._text_label.setText(new_text)
            bubble._text = new_text

    def _on_ai_response(self, response_text: str, success: bool):
        if self._streaming_bubble:
            self._update_bubble_text(self._streaming_bubble, response_text)

            if self._conversation and self._conversation[-1].get('content') == '思考中...':
                self._conversation[-1] = {"role": "assistant", "content": response_text}

        self._streaming_bubble = None
        self._streaming_text = ""
        self._worker = None

        self._is_processing = False
        self._input_bar.set_enabled(True)
        self._scroll_to_bottom()

    # ---- 快速操作 ----
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
        """AI 生成安全分析报告"""
        self._add_message('正在生成安全分析报告...', 'system')

        try:
            state = self.controller.get_state()
            llm = self.controller.llm

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

            if llm and llm.available_count > 0:
                analysis_prompt = (
                    f"请根据以下系统安全状态，生成一份简洁的安全分析报告（100字以内）:\n\n"
                    f"安全等级: {sec_level}\n"
                    f"活跃威胁数: {threats}\n"
                    f"可疑IP: {state.get('suspicious_ips', 0)}\n"
                    f"活跃连接: {state.get('active_connections', 0)}\n"
                    f"防火墙: {'开启' if fw else '关闭'}\n"
                    f"杀毒: {'开启' if av else '关闭'}\n"
                    f"CPU: {cpu:.1f}% / 内存: {mem:.1f}%\n"
                    f"最近事件: {state.get('messages', [])}\n\n"
                    f"请给出: 1)总体评价 2)主要风险 3)优先处理事项"
                )

                self._is_processing = True
                self._input_bar.set_enabled(False)

                analysis_bubble = self._add_message('AI 分析中...', 'ai')

                self._analysis_worker = LLMWorker(llm, [
                    {"role": "user", "content": analysis_prompt}
                ], self)
                self._analysis_worker.streaming.connect(
                    lambda chunk: self._on_report_chunk(chunk, analysis_bubble))
                self._analysis_worker.finished.connect(
                    lambda text, ok: self._on_report_done(text, ok, analysis_bubble))
                self._analysis_worker.start()
            else:
                self._add_message(
                    '配置 AI 模型后可获得智能安全分析报告。\n'
                    '当前显示的是系统实时数据摘要。', 'system')
        except Exception as e:
            self._add_message(f'报告生成失败: {e}', 'system')

    def _on_report_chunk(self, chunk: str, bubble: ChatBubble):
        self._update_bubble_text(bubble, bubble._text.replace('AI 分析中...', '') + chunk)

    def _on_report_done(self, text: str, success: bool, bubble: ChatBubble):
        if success:
            self._update_bubble_text(bubble, text)
        else:
            self._update_bubble_text(bubble, f'分析失败: {text}')
        self._is_processing = False
        self._input_bar.set_enabled(True)

    def _do_fix_advice(self):
        """获取安全修复建议"""
        self._add_message('正在分析修复方案...', 'system')

        try:
            state = self.controller.get_state()
            llm = self.controller.llm

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
            if state.get('mem_usage', 0) > 80:
                issues.append(f"内存使用率过高 ({state.get('mem_usage', 0):.0f}%)")

            if not issues:
                self._add_message(
                    '当前系统状态良好，未发现需要修复的问题。\n\n'
                    '日常安全建议:\n'
                    '  保持 Windows 和软件更新\n'
                    '  定期运行 Windows Defender 全盘扫描\n'
                    '  谨慎下载和运行未知来源的程序\n'
                    '  定期备份重要数据\n'
                    '  使用强密码并开启双因素认证',
                    'system')
                return

            issues_text = '\n'.join(f'  - {i}' for i in issues)
            self._add_message(f'发现以下问题:\n{issues_text}', 'system')

            if llm and llm.available_count > 0:
                fix_prompt = (
                    f"用户的系统存在以下安全问题:\n{issues_text}\n\n"
                    f"请给出具体的、可操作的修复建议（100字以内）。"
                    f"按优先级排序，说明每一步该怎么做。"
                )

                self._is_processing = True
                self._input_bar.set_enabled(False)
                fix_bubble = self._add_message('生成修复方案中...', 'ai')

                self._fix_worker = LLMWorker(llm, [
                    {"role": "user", "content": fix_prompt}
                ], self)
                self._fix_worker.streaming.connect(
                    lambda chunk: self._on_report_chunk(chunk, fix_bubble))
                self._fix_worker.finished.connect(
                    lambda text, ok: self._on_report_done(text, ok, fix_bubble))
                self._fix_worker.start()
            else:
                fix_lines = ['修复建议:']
                if not state.get('firewall_on', True):
                    fix_lines.append('\n开启防火墙:')
                    fix_lines.append('  1. 打开 Windows 设置 → 隐私和安全性 → Windows 安全中心')
                    fix_lines.append('  2. 点击"防火墙和网络保护"')
                    fix_lines.append('  3. 为所有网络配置文件开启防火墙')
                if not state.get('defender_on', True):
                    fix_lines.append('\n开启 Defender:')
                    fix_lines.append('  1. Windows 安全中心 → 病毒和威胁防护')
                    fix_lines.append('  2. 开启实时保护和云提供保护')
                if state.get('threat_count', 0) > 0:
                    fix_lines.append('\n处理威胁:')
                    fix_lines.append('  使用上方的"快速扫描"获取详细信息')
                    fix_lines.append(f'  当前有 {state.get("threat_count")} 个威胁需要关注')
                fix_lines.append('\n配置 AI 模型可获得个性化的修复指导。')

                self._add_message('\n'.join(fix_lines), 'ai')

        except Exception as e:
            self._add_message(f'分析失败: {e}', 'system')

    # ---- 看门狗 ----
    def _watchdog_check(self):
        """防止 _is_processing 永久卡死"""
        if self._is_processing and self._worker:
            import time
            if hasattr(self._worker, '_start_time'):
                elapsed = time.time() - self._worker._start_time
                if elapsed > 35:
                    self.logger.warning(f"LLM Worker 超时 ({elapsed:.0f}s)，强制终止")
                    if self._worker.isRunning():
                        self._worker.terminate()
                    self._on_ai_response("AI 响应超时，请稍后重试。", False)

    # ---- 窗口事件 ----
    def closeEvent(self, event):
        self._watchdog.stop()
        self._save_to_kb()
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait(2000)
        super().closeEvent(event)


# ============================================================
# 入口函数
# ============================================================
def show_chat_window(controller, logger: logging.Logger = None, parent=None):
    """显示 AI 对话窗口"""
    if not HAS_PYQT5:
        print("PyQt5 未安装。请运行: pip install PyQt5")
        return None

    chat = ChatWindow(controller, logger, parent)
    chat.setAttribute(Qt.WA_DeleteOnClose)
    chat.show()
    return chat


# ============================================================
# 独立测试
# ============================================================
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
        def chat_stream(self, messages, system_prompt, max_tokens):
            yield "模拟 AI 回复..."
        def chat(self, messages, system_prompt, max_tokens):
            class Resp:
                success = True
                text = "这是模拟的 AI 回复。"
            return Resp()
        def analyze_security_event(self, state):
            return "系统安全。"
        def generate_companion_line(self, state):
            return "一切正常~"

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
