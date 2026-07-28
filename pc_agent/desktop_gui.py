"""
AI 网络安全管家 - 桌面 GUI 应用
极简清爽风格 · 暗色主题 · 实时监控仪表盘 · 系统托盘后台运行
"""

import sys
import logging
from datetime import datetime

try:
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QFrame, QLabel,
        QVBoxLayout, QHBoxLayout, QGridLayout, QProgressBar,
        QListWidget, QListWidgetItem, QSystemTrayIcon, QMenu,
        QAction, QScrollArea, QSizePolicy, QSpacerItem, QPushButton,
        QGraphicsDropShadowEffect
    )
    from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, pyqtProperty, QPoint
    from PyQt5.QtGui import (
        QIcon, QPixmap, QPainter, QColor, QPen, QBrush,
        QFont, QPolygon, QFontDatabase
    )
    HAS_PYQT5 = True
except ImportError:
    HAS_PYQT5 = False
    # Stub base classes to prevent NameError when module is imported without PyQt5
    QApplication = QMainWindow = QWidget = QFrame = QLabel = object
    QVBoxLayout = QHBoxLayout = QGridLayout = QProgressBar = object
    QListWidget = QListWidgetItem = QSystemTrayIcon = QMenu = object
    QAction = QScrollArea = QSizePolicy = QSpacerItem = QPushButton = object
    QGraphicsDropShadowEffect = object
    QTimer = QPropertyAnimation = pyqtProperty = QPoint = object
    QIcon = QPixmap = QPainter = QColor = QPen = QBrush = object
    QFont = QPolygon = QFontDatabase = object
    Qt = type('Qt', (), {})()


# ============================================================
# 颜色常量 — 极简清爽调色板
# ============================================================
COLORS = {
    'bg_primary':     '#0d0f12',   # 主背景 - 极深柔黑
    'bg_card':        '#15181d',   # 卡片背景 - 柔深灰
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
    'white':          '#ffffff',
}

# ============================================================
# QSS 极简清爽主题
# ============================================================
DARK_THEME_QSS = """
QMainWindow, QWidget#centralWidget, QScrollArea,
QScrollArea > QWidget > QWidget {
    background-color: #0d0f12;
}

QScrollBar:vertical {
    background: transparent;
    width: 6px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #2d3340;
    border-radius: 3px;
    min-height: 40px;
}
QScrollBar::handle:vertical:hover {
    background: #3b82f6;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}

QFrame#statusCard {
    background-color: #15181d;
    border: none;
    border-radius: 10px;
}
QFrame#statusCard:hover {
    background-color: #1a1e24;
}

QFrame#statusCard[severity="danger"] {
    background-color: #1a1215;
}
QFrame#statusCard[severity="warning"] {
    background-color: #1a1610;
}

QLabel#cardIcon {
    font-size: 18px;
    qproperty-alignment: AlignLeft;
}
QLabel#cardValue {
    font-size: 28px;
    font-weight: 600;
    color: #e4e7eb;
    qproperty-alignment: AlignLeft;
}
QLabel#cardLabel {
    font-size: 11px;
    color: #8b919e;
    letter-spacing: 1px;
    qproperty-alignment: AlignLeft;
}

QLabel#sectionTitle {
    font-size: 12px;
    font-weight: 600;
    color: #8b919e;
    letter-spacing: 2px;
}

QLabel#headerTitle {
    font-size: 18px;
    font-weight: 600;
    color: #e4e7eb;
    letter-spacing: 0.5px;
}

QLabel#headerSubtitle {
    font-size: 11px;
    color: #5c6370;
    letter-spacing: 1px;
}

QProgressBar {
    background-color: #1c2026;
    border: none;
    border-radius: 3px;
    height: 4px;
}
QProgressBar::chunk {
    border-radius: 3px;
    background-color: #10b981;
}

QListWidget {
    background-color: transparent;
    border: none;
    padding: 0;
    outline: none;
}
QListWidget::item {
    background-color: #15181d;
    border: none;
    border-left: 2px solid #f59e0b;
    border-radius: 6px;
    padding: 10px 14px;
    margin: 3px 0px;
    color: #e4e7eb;
    font-size: 12px;
}
QListWidget::item:hover {
    background-color: #1a1e24;
}

QMenu {
    background-color: #15181d;
    border: 1px solid #22262e;
    border-radius: 8px;
    padding: 6px;
    color: #e4e7eb;
}
QMenu::item {
    padding: 6px 28px;
    border-radius: 4px;
    font-size: 12px;
}
QMenu::item:selected {
    background-color: #1c2026;
}
QMenu::separator {
    height: 1px;
    background: #22262e;
    margin: 4px 8px;
}
QMenu::item:disabled {
    color: #5c6370;
}

QToolTip {
    background-color: #15181d;
    border: 1px solid #22262e;
    border-radius: 4px;
    padding: 6px 10px;
    color: #e4e7eb;
    font-size: 11px;
}
"""


# ============================================================
# 图标生成 (QPainter)
# ============================================================
def create_shield_icon(color_hex: str, size: int = 64) -> QIcon:
    """用 QPainter 绘制极简盾牌图标"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    color = QColor(color_hex)

    from PyQt5.QtCore import QPoint
    poly = QPolygon([
        QPoint(size // 2, size // 10),
        QPoint(size - size // 10, size // 4),
        QPoint(size - size // 10, size // 2 + size // 10),
        QPoint(size // 2 + size // 8, size - size // 10),
        QPoint(size // 2, size - size // 8),
        QPoint(size // 2 - size // 8, size - size // 10),
        QPoint(size // 10, size // 2 + size // 10),
        QPoint(size // 10, size // 4),
    ])
    painter.setBrush(QBrush(color))
    painter.setPen(Qt.NoPen)
    painter.drawPolygon(poly)

    # 白色勾选
    pen = QPen(QColor('#ffffff'))
    pen.setWidth(3)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    check_x, check_y = size // 3, size // 2 + size // 16
    painter.drawLine(check_x, check_y, size // 2, size // 2 + size // 6)
    painter.drawLine(size // 2, size // 2 + size // 6, size - size // 4, size // 3)

    painter.end()
    return QIcon(pixmap)


def add_shadow(widget, blur=20, y_offset=2, color=QColor(0, 0, 0, 40)):
    """为控件添加柔和阴影"""
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(blur)
    shadow.setOffset(0, y_offset)
    shadow.setColor(color)
    widget.setGraphicsEffect(shadow)


# ============================================================
# StatusCard — 极简指标卡片
# ============================================================
class StatusCard(QFrame):
    """极简卡片: 图标行 + 大数值 + 小标签，左对齐排版"""

    def __init__(self, icon_text: str, value_text: str, label_text: str,
                 value_color: str = COLORS['text_primary'], parent=None):
        super().__init__(parent)
        self.setObjectName('statusCard')
        self._value_color = value_color
        self.setFixedHeight(96)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(6)

        # 顶部: 图标 + 标签同行
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self._icon = QLabel(icon_text)
        self._icon.setObjectName('cardIcon')
        top_row.addWidget(self._icon)

        self._label = QLabel(label_text.upper())
        self._label.setObjectName('cardLabel')
        top_row.addWidget(self._label)
        top_row.addStretch()
        layout.addLayout(top_row)

        # 大数值
        self._value = QLabel(value_text)
        self._value.setObjectName('cardValue')
        self._value.setStyleSheet(f"color: {value_color};")
        layout.addWidget(self._value)

        layout.addStretch()

    def update_value(self, text: str, color: str = None):
        self._value.setText(text)
        if color:
            self._value.setStyleSheet(f"color: {color};")
            self._value_color = color

    def set_severity(self, level: str):
        self.setProperty('severity', level)
        self.style().unpolish(self)
        self.style().polish(self)

    def update_icon(self, text: str):
        self._icon.setText(text)


# ============================================================
# GaugeCard — 极简资源进度卡片
# ============================================================
class GaugeCard(QFrame):
    """带细进度条的系统资源卡片"""

    def __init__(self, icon_text: str, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName('statusCard')
        self.setFixedHeight(96)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        # 顶部行
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        self._icon = QLabel(icon_text)
        self._icon.setObjectName('cardIcon')
        top_row.addWidget(self._icon)

        self._title = QLabel(title.upper())
        self._title.setObjectName('cardLabel')
        top_row.addWidget(self._title)
        top_row.addStretch()
        layout.addLayout(top_row)

        # 数值行 + 进度条
        self._percent = QLabel('0%')
        self._percent.setObjectName('cardValue')
        self._percent.setStyleSheet(f"color: {COLORS['text_primary']};")
        layout.addWidget(self._percent)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(4)
        self._bar.setStyleSheet(self._bar_style(COLORS['safe']))
        layout.addWidget(self._bar)

        layout.addStretch()

    @staticmethod
    def _bar_style(color: str) -> str:
        return f"""
        QProgressBar {{
            background-color: #1c2026;
            border: none;
            border-radius: 3px;
            height: 4px;
        }}
        QProgressBar::chunk {{
            background-color: {color};
            border-radius: 3px;
        }}
        """

    def set_value(self, percent: float):
        p = max(0.0, min(100.0, percent))
        self._bar.setValue(int(p))
        self._percent.setText(f'{p:.0f}%')

        if p >= 80:
            c = COLORS['danger']
        elif p >= 60:
            c = COLORS['warning']
        else:
            c = COLORS['safe']

        self._bar.setStyleSheet(self._bar_style(c))
        self._percent.setStyleSheet(f"color: {c};")


# ============================================================
# Divider — 极细分隔线
# ============================================================
class Divider(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setStyleSheet(f"background-color: {COLORS['border']};")


# ============================================================
# DesktopGUI — 主窗口
# ============================================================
class DesktopGUI(QMainWindow):
    """AI 网络安全管家桌面主窗口 — 极简清爽版"""

    def __init__(self, controller, logger: logging.Logger = None):
        super().__init__()
        self.controller = controller
        self.logger = logger or logging.getLogger(__name__)
        self._pulse_state = False
        self._pulse_timer = None
        self._first_hide = True
        self._device_screen = 0  # 0=角色, 1=仪表盘

        self._build_ui()
        self._setup_tray()
        self._setup_timers()

    # ---- UI 构建 ----
    def _build_ui(self):
        self.setWindowTitle('AI 网络安全管家')
        self.setMinimumSize(920, 640)
        self.resize(1040, 720)
        self.setWindowIcon(create_shield_icon(COLORS['safe']))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName('centralWidget')
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        container.setObjectName('centralWidget')
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(32, 24, 32, 24)
        main_layout.setSpacing(0)

        # ======== 顶部标题区 ========
        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)

        title_row = QHBoxLayout()
        title = QLabel('AI 网络安全管家')
        title.setObjectName('headerTitle')
        title_row.addWidget(title)
        title_row.addStretch()

        # 连接指示
        self._conn_dot = QLabel('●')
        self._conn_dot.setStyleSheet(
            f"color: {COLORS['safe']}; font-size: 8px;")
        title_row.addWidget(self._conn_dot)

        self._conn_label = QLabel('已连接')
        self._conn_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11px; letter-spacing: 1px;")
        title_row.addWidget(self._conn_label)
        header_layout.addLayout(title_row)

        subtitle = QLabel('REAL-TIME SECURITY MONITOR')
        subtitle.setObjectName('headerSubtitle')
        header_layout.addWidget(subtitle)

        main_layout.addLayout(header_layout)
        main_layout.addSpacing(20)

        # 分隔线
        main_layout.addWidget(Divider())
        main_layout.addSpacing(20)

        # ======== 控制栏 ========
        ctrl_bar = QHBoxLayout()
        ctrl_bar.setSpacing(10)

        self._screen_btn = self._make_btn('设备屏幕切换')
        self._screen_btn.clicked.connect(self._toggle_device_screen)
        ctrl_bar.addWidget(self._screen_btn)

        self._screen_label = QLabel('开发板 · 表情屏')
        self._screen_label.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; letter-spacing: 1px;")
        ctrl_bar.addWidget(self._screen_label)

        ctrl_bar.addStretch()

        self._chat_btn = self._make_btn('AI 对话', primary=True)
        self._chat_btn.setCursor(Qt.PointingHandCursor)
        self._chat_btn.clicked.connect(self._open_chat_window)
        ctrl_bar.addWidget(self._chat_btn)

        self._chat_window = None

        main_layout.addLayout(ctrl_bar)
        main_layout.addSpacing(24)

        # ======== 第一行: 核心安全指标 ========
        sec_title = QLabel('安全概览')
        sec_title.setObjectName('sectionTitle')
        main_layout.addWidget(sec_title)
        main_layout.addSpacing(12)

        row1 = QHBoxLayout()
        row1.setSpacing(12)
        self._sec_card = StatusCard('○', 'SAFE', '安全等级', COLORS['safe'])
        self._threat_card = StatusCard('!', '0', '活跃威胁', COLORS['text_primary'])
        self._net_card = StatusCard('~', '正常', '网络状态', COLORS['safe'])
        self._ai_card = StatusCard('◆', '空闲', 'AI 状态', COLORS['text_secondary'])
        for card in [self._sec_card, self._threat_card, self._net_card, self._ai_card]:
            row1.addWidget(card)
        main_layout.addLayout(row1)
        main_layout.addSpacing(24)

        # ======== 第二行: 系统防护 + 资源 ========
        sys_title = QLabel('系统与资源')
        sys_title.setObjectName('sectionTitle')
        main_layout.addWidget(sys_title)
        main_layout.addSpacing(12)

        row2 = QHBoxLayout()
        row2.setSpacing(12)
        self._fw_card = StatusCard('◇', '开启', '防火墙', COLORS['safe'])
        self._av_card = StatusCard('◇', '开启', '防病毒', COLORS['safe'])
        self._cpu_gauge = GaugeCard('▣', 'CPU')
        self._mem_gauge = GaugeCard('▤', '内存')
        for card in [self._fw_card, self._av_card, self._cpu_gauge, self._mem_gauge]:
            row2.addWidget(card)
        main_layout.addLayout(row2)
        main_layout.addSpacing(24)

        # ======== 威胁消息区 ========
        threat_title = QLabel('威胁与事件')
        threat_title.setObjectName('sectionTitle')
        main_layout.addWidget(threat_title)
        main_layout.addSpacing(12)

        self._threat_list = QListWidget()
        self._threat_list.setMinimumHeight(120)
        self._threat_list.setMaximumHeight(200)
        main_layout.addWidget(self._threat_list)
        main_layout.addSpacing(24)

        # ======== 底部状态栏 ========
        main_layout.addWidget(Divider())
        main_layout.addSpacing(12)

        footer = QHBoxLayout()
        self._footer_label = QLabel('')
        self._footer_label.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; letter-spacing: 0.5px;")
        footer.addWidget(self._footer_label)
        footer.addStretch()

        version = QLabel('v3.0 · MINIMAL')
        version.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px; letter-spacing: 1px;")
        footer.addWidget(version)
        main_layout.addLayout(footer)

        main_layout.addStretch()

        scroll.setWidget(container)
        self.setCentralWidget(scroll)

    def _make_btn(self, text: str, primary: bool = False) -> QPushButton:
        """创建极简按钮"""
        btn = QPushButton(text)
        if primary:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['accent']};
                    color: {COLORS['white']};
                    border: none;
                    border-radius: 6px;
                    padding: 8px 18px;
                    font-size: 12px;
                    font-weight: 600;
                    letter-spacing: 1px;
                }}
                QPushButton:hover {{
                    background-color: #2563eb;
                }}
            """)
        else:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {COLORS['text_secondary']};
                    border: 1px solid {COLORS['border']};
                    border-radius: 6px;
                    padding: 8px 16px;
                    font-size: 12px;
                    letter-spacing: 1px;
                }}
                QPushButton:hover {{
                    background-color: {COLORS['bg_card']};
                    color: {COLORS['text_primary']};
                    border-color: {COLORS['border_focus']};
                }}
            """)
        return btn

    # ---- 系统托盘 ----
    def _setup_tray(self):
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(create_shield_icon(COLORS['safe']))
        self._tray.setToolTip('AI 网络安全管家')

        menu = QMenu()
        show_action = menu.addAction('显示窗口')
        show_action.triggered.connect(self._show_window)
        menu.addSeparator()

        self._tray_status = QAction('状态 · 安全', menu)
        self._tray_status.setEnabled(False)
        menu.addAction(self._tray_status)

        self._tray_threats = QAction('威胁 · 0', menu)
        self._tray_threats.setEnabled(False)
        menu.addAction(self._tray_threats)

        self._tray_ai = QAction('AI · 空闲', menu)
        self._tray_ai.setEnabled(False)
        menu.addAction(self._tray_ai)
        menu.addSeparator()

        quit_action = menu.addAction('退出')
        quit_action.triggered.connect(self.quit_app)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick or reason == QSystemTrayIcon.Trigger:
            self._show_window()

    def _show_window(self):
        self.show()
        self.raise_()
        self.activateWindow()

    # ---- 定时器 ----
    def _setup_timers(self):
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_dashboard)
        self._refresh_timer.start(2500)

        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._toggle_pulse)

    # ---- 核心刷新 ----
    def _refresh_dashboard(self):
        try:
            state = self.controller.get_state()
        except Exception as e:
            self._footer_label.setText(f'获取状态失败: {e}')
            return

        sec_level = state.get('sec_level', 'safe')

        # 安全等级卡片
        sec_label = sec_level.upper()
        sec_color = {'safe': COLORS['safe'], 'warning': COLORS['warning'],
                      'danger': COLORS['danger']}.get(sec_level, COLORS['safe'])
        sec_icon = {'safe': '○', 'warning': '◐', 'danger': '●'}.get(sec_level, '○')
        self._sec_card.update_value(sec_label, sec_color)
        self._sec_card.update_icon(sec_icon)
        self._sec_card.set_severity(sec_level)

        # 危险脉冲
        if sec_level == 'danger' and not self._pulse_timer.isActive():
            self._pulse_timer.start(1500)
        elif sec_level != 'danger' and self._pulse_timer.isActive():
            self._pulse_timer.stop()
            self._sec_card.set_severity(sec_level)

        # 威胁计数
        threat_count = state.get('threat_count', 0)
        threat_color = COLORS['danger'] if threat_count > 0 else COLORS['text_primary']
        self._threat_card.update_value(str(threat_count), threat_color)
        self._threat_card.update_icon('!' if threat_count > 0 else '✓')

        # AI 状态
        ai_status = state.get('ai_status', 'idle')
        ai_map = {
            'idle': ('空闲', COLORS['text_secondary'], '◆'),
            'working': ('工作中', COLORS['accent'], '◈'),
            'alert': ('警报', COLORS['danger'], '▲'),
            'offline': ('离线', COLORS['text_muted'], '◇'),
        }
        ai_label, ai_color, ai_icon = ai_map.get(ai_status, ('空闲', COLORS['text_secondary'], '◆'))
        self._ai_card.update_value(ai_label, ai_color)
        self._ai_card.update_icon(ai_icon)

        # 网络状态
        net_status = state.get('net_status', 'normal')
        net_map = {
            'normal': ('正常', COLORS['safe'], '~'),
            'suspicious': ('可疑', COLORS['warning'], '≈'),
            'under_attack': ('受攻击', COLORS['danger'], '⚡'),
        }
        net_label, net_color, net_icon = net_map.get(net_status, ('正常', COLORS['safe'], '~'))
        self._net_card.update_value(net_label, net_color)
        self._net_card.update_icon(net_icon)

        # 防火墙
        fw_on = state.get('firewall_on', True)
        self._fw_card.update_value(
            '开启' if fw_on else '关闭',
            COLORS['safe'] if fw_on else COLORS['danger'])
        self._fw_card.update_icon('●' if fw_on else '○')
        if not fw_on:
            self._fw_card.set_severity('danger')

        # 防病毒
        av_on = state.get('defender_on', True)
        self._av_card.update_value(
            '开启' if av_on else '关闭',
            COLORS['safe'] if av_on else COLORS['danger'])
        self._av_card.update_icon('●' if av_on else '○')
        if not av_on:
            self._av_card.set_severity('danger')

        # CPU / 内存
        self._cpu_gauge.set_value(state.get('cpu_usage', 0))
        self._mem_gauge.set_value(state.get('mem_usage', 0))

        # 活跃连接数
        active_conns = state.get('active_connections', 0)
        suspicious = state.get('suspicious_ips', 0)

        # 威胁消息列表
        messages = state.get('messages', [])
        self._threat_list.clear()
        if messages:
            for msg in messages:
                item = QListWidgetItem(f'   {msg}')
                self._threat_list.addItem(item)
        else:
            item = QListWidgetItem('   系统运行正常，无活跃威胁')
            item.setForeground(QColor(COLORS['text_muted']))
            self._threat_list.addItem(item)

        # 底部状态
        uptime_s = state.get('uptime', 0)
        now = datetime.now().strftime('%H:%M:%S')
        self._footer_label.setText(
            f'刷新 {now}  ·  连接 {active_conns}  ·  可疑IP {suspicious}  ·  运行 {self._format_uptime(uptime_s)}')

        # 连接状态
        self._conn_dot.setStyleSheet(f"color: {COLORS['safe']}; font-size: 8px;")
        self._conn_label.setText('已连接')

        # 托盘
        tray_color = {'safe': COLORS['safe'], 'warning': COLORS['warning'],
                       'danger': COLORS['danger']}.get(sec_level, COLORS['safe'])
        self._tray.setIcon(create_shield_icon(tray_color))
        self._tray_status.setText(
            f"状态 · {'危险' if sec_level == 'danger' else '警告' if sec_level == 'warning' else '安全'}")
        self._tray_threats.setText(f'威胁 · {threat_count}')
        self._tray_ai.setText(f'AI · {ai_label}')

    # ---- AI 对话窗口 ----
    def _open_chat_window(self):
        try:
            from chat_window import ChatWindow
        except ImportError:
            self.logger.error("无法导入 AI 对话模块")
            return

        if self._chat_window is not None:
            try:
                self._chat_window.close()
            except Exception:
                pass

        self._chat_window = ChatWindow(self.controller, self.logger, self)
        self._chat_window.setAttribute(Qt.WA_DeleteOnClose)
        self._chat_window.destroyed.connect(lambda: setattr(self, '_chat_window', None))
        self._chat_window.show()
        self._chat_window.raise_()
        self._chat_window.activateWindow()
        self.logger.info('打开 AI 对话窗口')

    # ---- 设备屏幕切换 ----
    def _toggle_device_screen(self):
        self._device_screen = 1 - self._device_screen
        try:
            self.controller.device.send_command({
                "cmd": "screen",
                "screen": self._device_screen
            })
            label = '开发板 · 仪表盘' if self._device_screen else '开发板 · 表情屏'
            self._screen_label.setText(label)
            self.logger.info(f'切换开发板屏幕 → {"仪表盘" if self._device_screen else "角色屏"}')
        except Exception as e:
            self.logger.debug(f'切换屏幕失败: {e}')

    # ---- 脉冲动画 ----
    def _toggle_pulse(self):
        self._pulse_state = not self._pulse_state
        self._sec_card.setProperty('severity', 'danger' if self._pulse_state else 'safe')
        self._sec_card.style().unpolish(self._sec_card)
        self._sec_card.style().polish(self._sec_card)

    # ---- 工具方法 ----
    @staticmethod
    def _format_uptime(seconds: int) -> str:
        if seconds < 60:
            return f'{seconds}s'
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        d, h = divmod(h, 24)
        if d > 0:
            return f'{d}d {h}h'
        if h > 0:
            return f'{h}h {m}m'
        return f'{m}m'

    # ---- 窗口事件 ----
    def closeEvent(self, event):
        event.ignore()
        self.hide()
        if self._first_hide:
            self._tray.showMessage(
                'AI 网络安全管家',
                '已最小化到系统托盘\n双击图标恢复窗口',
                QSystemTrayIcon.Information, 3000)
            self._first_hide = False

    def changeEvent(self, event):
        from PyQt5.QtCore import QEvent as QtCoreEvent
        if event.type() == QtCoreEvent.WindowStateChange:
            if self.isMinimized():
                self.hide()
                event.ignore()
                return
        super().changeEvent(event)

    def quit_app(self):
        self._refresh_timer.stop()
        if self._pulse_timer.isActive():
            self._pulse_timer.stop()
        self._tray.hide()
        try:
            self.controller.stop()
        except Exception:
            pass
        QApplication.quit()


# ============================================================
# 入口
# ============================================================
def run_gui(controller, logger: logging.Logger = None) -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_THEME_QSS)
    app.setQuitOnLastWindowClosed(False)

    if logger is None:
        logger = logging.getLogger(__name__)

    gui = DesktopGUI(controller, logger)
    gui.show()

    return app.exec_()


# ============================================================
# 独立测试 (Mock Controller)
# ============================================================
if __name__ == '__main__':
    import random
    import time

    class MockController:
        def get_state(self):
            sec = random.choices(
                ['safe', 'warning', 'danger'], weights=[0.7, 0.2, 0.1])[0]
            return {
                'sec_level': sec,
                'threat_count': random.randint(0, 3) if sec != 'safe' else 0,
                'blocked_count': random.randint(0, 8),
                'last_threat': '',
                'active_connections': random.randint(3, 40),
                'suspicious_ips': random.randint(0, 2) if sec != 'safe' else 0,
                'net_status': 'normal' if sec == 'safe' else
                               'suspicious' if sec == 'warning' else 'under_attack',
                'firewall_on': random.choice([True, True, True, False]),
                'defender_on': random.choice([True, True, True, False]),
                'cpu_usage': random.uniform(5, 85),
                'mem_usage': random.uniform(25, 75),
                'uptime': int(time.time() - random.randint(0, 86400)),
                'messages': (['检测到可疑连接: 192.168.1.100:4444',
                               '进程 nmap.exe 疑似扫描行为'] if sec != 'safe' else []),
                'ai_status': random.choice(['idle', 'idle', 'working']),
                'ai_task': '',
                'ai_progress': 0,
            }

        def stop(self):
            pass

    run_gui(MockController())
