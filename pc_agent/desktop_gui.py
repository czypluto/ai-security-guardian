"""
AI 网络安全管家 - 桌面 GUI 应用
PyQt5 深色主题，实时监控仪表盘，系统托盘后台运行
"""

import sys
import logging
from datetime import datetime

try:
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QFrame, QLabel,
        QVBoxLayout, QHBoxLayout, QGridLayout, QProgressBar,
        QListWidget, QListWidgetItem, QSystemTrayIcon, QMenu,
        QAction, QScrollArea, QSizePolicy, QSpacerItem, QPushButton
    )
    from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, pyqtProperty
    from PyQt5.QtGui import (
        QIcon, QPixmap, QPainter, QColor, QPen, QBrush,
        QFont, QPolygon, QFontDatabase
    )
    HAS_PYQT5 = True
except ImportError:
    HAS_PYQT5 = False


# ============================================================
# 颜色常量
# ============================================================
COLORS = {
    'bg_primary':     '#0a0e17',
    'bg_card':        '#141b26',
    'bg_card_hover':  '#1a2433',
    'border':         '#1e2d3d',
    'border_focus':   '#4a9eff',
    'accent':         '#4a9eff',
    'safe':           '#00d4aa',
    'warning':        '#ffc107',
    'danger':         '#ff4757',
    'text_primary':   '#e0e6ed',
    'text_secondary': '#8899aa',
    'btn_bg':         '#1e3a5f',
    'btn_hover':      '#2a5088',
    'white':          '#ffffff',
}

# ============================================================
# QSS 暗色主题样式表
# ============================================================
DARK_THEME_QSS = """
QMainWindow {
    background-color: #0a0e17;
}

QWidget#centralWidget {
    background-color: #0a0e17;
}

QScrollArea {
    background-color: #0a0e17;
    border: none;
}

QScrollArea > QWidget > QWidget {
    background-color: #0a0e17;
}

QScrollBar:vertical {
    background: #141b26;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #2a5088;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QFrame#statusCard {
    background-color: #141b26;
    border: 1px solid #1e2d3d;
    border-radius: 12px;
    padding: 16px;
}
QFrame#statusCard:hover {
    border-color: #4a9eff;
}

QFrame#statusCard[severity="danger"] {
    border-color: #ff4757;
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #141b26, stop:0.9 #141b26, stop:1 #2a1520);
}
QFrame#statusCard[severity="warning"] {
    border-color: #ffc107;
}

QLabel#cardIcon {
    font-size: 32px;
    qproperty-alignment: AlignCenter;
}
QLabel#cardValue {
    font-size: 26px;
    font-weight: bold;
    color: #e0e6ed;
    qproperty-alignment: AlignCenter;
    margin: 4px 0px;
}
QLabel#cardLabel {
    font-size: 11px;
    color: #8899aa;
    text-transform: uppercase;
    qproperty-alignment: AlignCenter;
}

QLabel#sectionTitle {
    font-size: 14px;
    font-weight: bold;
    color: #4a9eff;
    padding-bottom: 8px;
}

QLabel#headerTitle {
    font-size: 22px;
    font-weight: bold;
    color: #4a9eff;
}

QLabel#statusDot {
    font-size: 12px;
    color: #00d4aa;
}

QProgressBar {
    background-color: #1e2d3d;
    border: none;
    border-radius: 6px;
    height: 10px;
    text-align: center;
}
QProgressBar::chunk {
    border-radius: 6px;
    background-color: #00d4aa;
}

QListWidget {
    background-color: #141b26;
    border: 1px solid #1e2d3d;
    border-radius: 8px;
    padding: 4px;
    outline: none;
}
QListWidget::item {
    background-color: #1a1e2a;
    border-left: 3px solid #ffc107;
    border-radius: 4px;
    padding: 8px 12px;
    margin: 2px 0px;
    color: #e0e6ed;
    font-size: 12px;
}
QListWidget::item:hover {
    background-color: #1e2430;
}

QMenu {
    background-color: #141b26;
    border: 1px solid #1e2d3d;
    border-radius: 8px;
    padding: 4px;
    color: #e0e6ed;
}
QMenu::item {
    padding: 6px 24px;
    border-radius: 4px;
}
QMenu::item:selected {
    background-color: #1e3a5f;
}
QMenu::separator {
    height: 1px;
    background: #1e2d3d;
    margin: 4px 12px;
}
QMenu::item:disabled {
    color: #8899aa;
}

QToolTip {
    background-color: #141b26;
    border: 1px solid #1e2d3d;
    border-radius: 4px;
    padding: 4px 8px;
    color: #e0e6ed;
    font-size: 11px;
}
"""


# ============================================================
# 图标生成 (QPainter 替代 PIL)
# ============================================================
def create_shield_icon(color_hex: str, size: int = 64) -> QIcon:
    """用 QPainter 绘制盾牌+勾选图标"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    color = QColor(color_hex)

    # 盾牌多边形 (QPoint 列表)
    from PyQt5.QtCore import QPoint
    poly = QPolygon([
        QPoint(size // 2, size // 10),                    # 顶部
        QPoint(size - size // 10, size // 4),              # 右上
        QPoint(size - size // 10, size // 2 + size // 10), # 右下
        QPoint(size // 2 + size // 8, size - size // 10), # 右下角
        QPoint(size // 2, size - size // 8),              # 底部尖端
        QPoint(size // 2 - size // 8, size - size // 10), # 左下角
        QPoint(size // 10, size // 2 + size // 10),       # 左下
        QPoint(size // 10, size // 4),                     # 左上
    ])
    painter.setBrush(QBrush(color))
    painter.setPen(QPen(color.darker(120), 2))
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


# ============================================================
# StatusCard — 通用指标卡片
# ============================================================
class StatusCard(QFrame):
    """显示单个安全指标的卡片: 图标 + 数值 + 标签"""

    def __init__(self, icon_text: str, value_text: str, label_text: str,
                 value_color: str = COLORS['text_primary'], parent=None):
        super().__init__(parent)
        self.setObjectName('statusCard')
        self._value_color = value_color

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(6)

        self._icon = QLabel(icon_text)
        self._icon.setObjectName('cardIcon')
        self._icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._icon)

        self._value = QLabel(value_text)
        self._value.setObjectName('cardValue')
        self._value.setAlignment(Qt.AlignCenter)
        self._value.setStyleSheet(f"color: {value_color};")
        layout.addWidget(self._value)

        self._label = QLabel(label_text)
        self._label.setObjectName('cardLabel')
        self._label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._label)

        layout.addStretch()

    def update_value(self, text: str, color: str = None):
        """更新卡片数值"""
        self._value.setText(text)
        if color:
            self._value.setStyleSheet(f"color: {color};")
            self._value_color = color

    def set_severity(self, level: str):
        """设置严重等级 (safe / warning / danger)，触发 QSS 动态样式"""
        self.setProperty('severity', level)
        self.style().unpolish(self)
        self.style().polish(self)


# ============================================================
# GaugeCard — CPU/内存进度条卡片
# ============================================================
class GaugeCard(QFrame):
    """带进度条的系统资源卡片"""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName('statusCard')

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(6)

        # 图标
        icon = QLabel('📊')
        icon.setObjectName('cardIcon')
        icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon)

        # 标题
        self._title = QLabel(title)
        self._title.setObjectName('cardLabel')
        self._title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._title)

        # 百分比文字
        self._percent = QLabel('0%')
        self._percent.setObjectName('cardValue')
        self._percent.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._percent)

        # 进度条
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(10)
        self._bar.setStyleSheet(self._bar_chunk_style(COLORS['safe']))
        layout.addWidget(self._bar)

        layout.addStretch()

    @staticmethod
    def _bar_chunk_style(color: str) -> str:
        return f"""
        QProgressBar::chunk {{
            background-color: {color};
            border-radius: 6px;
        }}
        """

    def set_value(self, percent: float):
        """更新进度条值和颜色"""
        p = max(0.0, min(100.0, percent))
        self._bar.setValue(int(p))
        self._percent.setText(f'{p:.1f}%')

        if p >= 80:
            chunk_color = COLORS['danger']
        elif p >= 60:
            chunk_color = COLORS['warning']
        else:
            chunk_color = COLORS['safe']

        css = f"""
        QProgressBar::chunk {{
            background-color: {chunk_color};
            border-radius: 6px;
        }}
        QProgressBar {{
            background-color: #1e2d3d;
            border: none;
            border-radius: 6px;
            height: 10px;
        }}
        """
        self._bar.setStyleSheet(css)
        self._percent.setStyleSheet(f"color: {chunk_color};")


# ============================================================
# DesktopGUI — 主窗口
# ============================================================
class DesktopGUI(QMainWindow):
    """AI 网络安全管家桌面主窗口"""

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
        self.setWindowTitle('🛡️ AI 网络安全管家')
        self.setMinimumSize(880, 620)
        self.resize(1000, 700)
        self.setWindowIcon(create_shield_icon(COLORS['safe']))

        # 可滚动中央区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName('centralWidget')

        container = QWidget()
        container.setObjectName('centralWidget')
        main_layout = QVBoxLayout(container)
        main_layout.setContentsMargins(24, 16, 24, 16)
        main_layout.setSpacing(14)

        # --- 标题栏 ---
        header = QHBoxLayout()
        title = QLabel('🛡️ AI 网络安全管家')
        title.setObjectName('headerTitle')
        header.addWidget(title)
        header.addStretch()

        self._conn_dot = QLabel('●')
        self._conn_dot.setObjectName('statusDot')
        self._conn_dot.setStyleSheet(f"color: {COLORS['safe']}; font-size: 12px;")
        header.addWidget(self._conn_dot)
        self._conn_label = QLabel(' 已连接')
        self._conn_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        header.addWidget(self._conn_label)
        main_layout.addLayout(header)

        # --- 控制栏 ---
        ctrl_bar = QHBoxLayout()
        ctrl_bar.setSpacing(8)

        self._screen_btn = QPushButton('🎵 角色 / 📊 仪表盘')
        self._screen_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['btn_bg']};
                color: {COLORS['accent']};
                border: 1px solid {COLORS['border_focus']};
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['btn_hover']};
            }}
        """)
        self._screen_btn.clicked.connect(self._toggle_device_screen)
        ctrl_bar.addWidget(self._screen_btn)

        self._screen_label = QLabel('📺 开发板: 角色屏')
        self._screen_label.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px;")
        ctrl_bar.addWidget(self._screen_label)
        ctrl_bar.addStretch()
        main_layout.addLayout(ctrl_bar)

        # --- 第一行卡片 ---
        row1 = QHBoxLayout()
        row1.setSpacing(12)
        self._sec_card = StatusCard('🛡️', 'SAFE', '安全等级', COLORS['safe'])
        self._threat_card = StatusCard('⚠️', '0', '活跃威胁', COLORS['text_primary'])
        self._ai_card = StatusCard('🤖', 'Idle', 'AI 状态', COLORS['text_primary'])
        self._net_card = StatusCard('🌐', 'Normal', '网络状态', COLORS['safe'])
        for card in [self._sec_card, self._threat_card, self._ai_card, self._net_card]:
            row1.addWidget(card)
        main_layout.addLayout(row1)

        # --- 第二行卡片 ---
        row2 = QHBoxLayout()
        row2.setSpacing(12)
        self._fw_card = StatusCard('🔥', 'ON', '防火墙', COLORS['safe'])
        self._av_card = StatusCard('🛡️', 'ON', '防病毒', COLORS['safe'])
        self._cpu_gauge = GaugeCard('CPU')
        self._mem_gauge = GaugeCard('Memory')
        for card in [self._fw_card, self._av_card, self._cpu_gauge, self._mem_gauge]:
            row2.addWidget(card)
        main_layout.addLayout(row2)

        # --- 威胁消息区 ---
        threat_header = QLabel('🚨 威胁消息')
        threat_header.setObjectName('sectionTitle')
        main_layout.addWidget(threat_header)

        self._threat_list = QListWidget()
        self._threat_list.setMinimumHeight(130)
        self._threat_list.setMaximumHeight(200)
        main_layout.addWidget(self._threat_list)

        # --- 底部状态信息 ---
        footer = QHBoxLayout()
        self._footer_label = QLabel('')
        self._footer_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11px;")
        footer.addWidget(self._footer_label)
        footer.addStretch()
        version = QLabel('v2.1 GUI')
        version.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 11px;")
        footer.addWidget(version)
        main_layout.addLayout(footer)

        main_layout.addStretch()

        scroll.setWidget(container)
        self.setCentralWidget(scroll)

    # ---- 系统托盘 ----
    def _setup_tray(self):
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(create_shield_icon(COLORS['safe']))
        self._tray.setToolTip('AI 网络安全管家')

        # 菜单
        menu = QMenu()
        show_action = menu.addAction('📊 显示窗口')
        show_action.triggered.connect(self._show_window)
        menu.addSeparator()

        self._tray_status = QAction('状态: ● 安全', menu)
        self._tray_status.setEnabled(False)
        menu.addAction(self._tray_status)

        self._tray_threats = QAction('威胁: 0', menu)
        self._tray_threats.setEnabled(False)
        menu.addAction(self._tray_threats)

        self._tray_ai = QAction('AI: 空闲', menu)
        self._tray_ai.setEnabled(False)
        menu.addAction(self._tray_ai)
        menu.addSeparator()

        quit_action = menu.addAction('❌ 退出')
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
        # 主刷新定时器 (2.5s)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_dashboard)
        self._refresh_timer.start(2500)

        # 脉冲动画定时器 (1.5s, 默认不启动)
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
        self._sec_card.update_value(sec_label, sec_color)
        self._sec_card.set_severity(sec_level)

        # 危险脉冲动画
        if sec_level == 'danger' and not self._pulse_timer.isActive():
            self._pulse_timer.start(1500)
        elif sec_level != 'danger' and self._pulse_timer.isActive():
            self._pulse_timer.stop()
            self._sec_card.set_severity(sec_level)

        # 威胁计数
        threat_count = state.get('threat_count', 0)
        threat_color = COLORS['danger'] if threat_count > 0 else COLORS['text_primary']
        self._threat_card.update_value(str(threat_count), threat_color)

        # AI 状态
        ai_status = state.get('ai_status', 'idle')
        ai_emoji = self._get_char_emoji(sec_level, ai_status)
        self._ai_card._icon.setText(ai_emoji)
        self._ai_card.update_value(ai_status.title(), COLORS['text_primary'])

        # 网络状态
        net_status = state.get('net_status', 'normal')
        net_label = net_status.replace('_', ' ').title()
        net_color = {'normal': COLORS['safe'], 'suspicious': COLORS['warning'],
                      'under_attack': COLORS['danger']}.get(net_status, COLORS['safe'])
        self._net_card.update_value(net_label, net_color)

        # 防火墙
        fw_on = state.get('firewall_on', True)
        self._fw_card.update_value(
            '✅ ON' if fw_on else '❌ OFF',
            COLORS['safe'] if fw_on else COLORS['danger'])
        if not fw_on:
            self._fw_card.set_severity('danger')

        # 防病毒
        av_on = state.get('defender_on', True)
        self._av_card.update_value(
            '✅ ON' if av_on else '❌ OFF',
            COLORS['safe'] if av_on else COLORS['danger'])
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
                item = QListWidgetItem(f'▎ {msg}')
                self._threat_list.addItem(item)
        else:
            item = QListWidgetItem('▎ 无活跃威胁')
            item.setForeground(QColor(COLORS['text_secondary']))
            self._threat_list.addItem(item)

        # 底部状态
        uptime_s = state.get('uptime', 0)
        now = datetime.now().strftime('%H:%M:%S')
        self._footer_label.setText(
            f'刷新: {now}  |  连接: {active_conns}  |  可疑IP: {suspicious}  |  运行: {self._format_uptime(uptime_s)}')

        # 连接状态指示
        self._conn_dot.setStyleSheet(f"color: {COLORS['safe']}; font-size: 12px;")

        # 托盘图标颜色
        tray_color = {'safe': COLORS['safe'], 'warning': COLORS['warning'],
                       'danger': COLORS['danger']}.get(sec_level, COLORS['safe'])
        self._tray.setIcon(create_shield_icon(tray_color))
        self._tray_status.setText(
            f"状态: {'🔴' if sec_level == 'danger' else '🟡' if sec_level == 'warning' else '🟢'} {sec_label}")
        self._tray_threats.setText(f'威胁: {threat_count}')
        self._tray_ai.setText(f'AI: {ai_status}')

    # ---- 设备屏幕切换 ----
    def _toggle_device_screen(self):
        """切换 TTGO 开发板屏幕 (角色 ⇄ 仪表盘)"""
        self._device_screen = 1 - self._device_screen
        try:
            self.controller.device.send_command({
                "cmd": "screen",
                "screen": self._device_screen
            })
            label = '📺 开发板: 仪表盘' if self._device_screen else '📺 开发板: 角色屏'
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

    # ---- 角色表情 ----
    @staticmethod
    def _get_char_emoji(sec_level: str, ai_status: str) -> str:
        if sec_level == 'danger':
            return '(>_<)💢'
        if sec_level == 'warning':
            return '(;_;)⚡'
        if ai_status == 'working':
            return '(･_･)🛡️'
        if ai_status == 'alert':
            return '(>_<)'
        if ai_status == 'offline':
            return '(-_-)💤'
        return '(｡･ω･｡)✨'

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
        """关闭 → 最小化到托盘"""
        event.ignore()
        self.hide()
        if self._first_hide:
            self._tray.showMessage(
                'AI 网络安全管家',
                '已最小化到系统托盘。\n双击图标恢复窗口。',
                QSystemTrayIcon.Information, 3000)
            self._first_hide = False

    def changeEvent(self, event):
        """窗口最小化时隐藏到托盘"""
        from PyQt5.QtCore import QEvent as QtCoreEvent
        if event.type() == QtCoreEvent.WindowStateChange:
            if self.isMinimized():
                self.hide()
                event.ignore()
                return
        super().changeEvent(event)

    def quit_app(self):
        """完整退出"""
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
    """启动 PyQt5 桌面 GUI，返回 QApplication 退出码"""
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
        """模拟控制器，用于独立测试 GUI"""
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
