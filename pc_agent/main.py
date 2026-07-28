#!/usr/bin/env python3
"""
============================================================
 AI 网络安全管家 - PC Agent 主程序
 AI Network Security Guardian - Main Entry Point
============================================================

启动后会自动:
 1. 监控 Windows 安全状态
 2. 检测网络威胁
 3. 扫描可疑进程
 4. 检查防火墙/杀毒状态
 5. 将状态推送到 ESP32 设备
 6. 启动 Web Dashboard (可选)
"""

import sys
import os
import time
import signal
import threading
import logging
import argparse
from pathlib import Path

import yaml

from security_monitor import SecurityMonitor
from network_monitor import NetworkMonitor
from process_monitor import ProcessMonitor
from firewall_checker import FirewallChecker
from device_bridge import DeviceBridge
from ai_status import AIStatusTracker
from character_manager import CharacterManager
from llm_client import MultiLLMClient, LLMConfig, Provider, PRESET_MODELS

# 可选模块
try:
    from web_dashboard import WebDashboard
    HAS_DASHBOARD = True
except ImportError:
    HAS_DASHBOARD = False

try:
    from system_tray import SystemTrayApp
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

try:
    from desktop_gui import run_gui, HAS_PYQT5
    HAS_GUI = HAS_PYQT5
except ImportError:
    HAS_GUI = False

# ==================== 日志 ====================

def setup_logging(config: dict):
    """配置日志系统"""
    try:
        import colorlog
        _has_colorlog = True
    except ImportError:
        _has_colorlog = False

    log_config = config.get('logging', {})
    level = getattr(logging, log_config.get('level', 'INFO'))
    log_file = log_config.get('file', 'guardian.log')

    # 控制台 handler (彩色)
    if _has_colorlog:
        console_handler = colorlog.StreamHandler()
        console_handler.setFormatter(colorlog.ColoredFormatter(
            '%(log_color)s%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%H:%M:%S',
            log_colors={
                'DEBUG': 'cyan',
                'INFO': 'green',
                'WARNING': 'yellow',
                'ERROR': 'red',
                'CRITICAL': 'red,bg_white',
            }
        ))
    else:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
            datefmt='%H:%M:%S',
        ))

    # 文件 handler
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    ))

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    return logging.getLogger('Guardian')


# ==================== 主控制器 ====================

class GuardianController:
    """安全管家主控制器"""

    def __init__(self, config_path: str = None):
        self.config = self._load_config(config_path)
        self.logger = setup_logging(self.config)
        self.running = False
        self.state_lock = threading.Lock()

        # 全局状态 (推送到 ESP32)
        self.state = {
            'ai_status': 'idle',
            'ai_task': '',
            'ai_progress': 0,
            'sec_level': 'safe',
            'threat_count': 0,
            'blocked_count': 0,
            'last_threat': '',
            'active_connections': 0,
            'suspicious_ips': 0,
            'net_status': 'normal',
            'firewall_on': True,
            'defender_on': True,
            'cpu_usage': 0,
            'mem_usage': 0,
            'uptime': 0,
            'messages': [],
        }

        # 初始化模块
        self.device = DeviceBridge(self.config.get('device', {}), self.logger)
        self.ai_tracker = AIStatusTracker(self.config.get('ai', {}), self.logger)
        self.security = SecurityMonitor(self.config.get('security', {}), self.logger)
        self.network = NetworkMonitor(self.config.get('security', {}).get('network', {}), self.logger)
        self.process = ProcessMonitor(self.config.get('security', {}).get('process', {}), self.logger)
        self.firewall = FirewallChecker(self.config.get('security', {}).get('firewall', {}), self.logger)

        # LLM 客户端 (多模型支持)
        self.llm = self._init_llm_client()
        self.logger.info(f"🤖 LLM: {self.llm.available_count} 个模型可用")

        # 二次元角色管理器 (LLM 驱动)
        self.character = CharacterManager(self.logger, llm_client=self.llm)
        char_cfg = self.config.get('character', {})
        if char_cfg.get('config_file'):
            self.character.load_character(char_cfg['config_file'])
        self._last_sec_level = 'safe'
        self._startup_phase = True

        self.web = None
        if HAS_DASHBOARD and self.config.get('dashboard', {}).get('enabled', False):
            self.web = WebDashboard(self.config.get('dashboard', {}), self, self.logger)

        self.tray = None
        if HAS_TRAY and self.config.get('system_tray', {}).get('enabled', False):
            self.tray = SystemTrayApp(self, self.logger)

    def _load_config(self, config_path: str = None) -> dict:
        """加载配置文件"""
        if config_path is None:
            config_path = Path(__file__).parent / 'config.yaml'
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def _init_llm_client(self) -> MultiLLMClient:
        """初始化多模型 LLM 客户端"""
        llm_cfg = self.config.get('llm', {})
        if not llm_cfg.get('enabled', True):
            self.logger.info("LLM 功能已禁用")
            return MultiLLMClient([], self.logger)

        client = MultiLLMClient([], self.logger)
        default_model = llm_cfg.get('default_model', 'glm-4-flash')

        # DeepSeek
        ds_cfg = llm_cfg.get('deepseek', {})
        if ds_cfg.get('enabled') and ds_cfg.get('api_key', '').startswith('sk-'):
            client.add_from_preset(ds_cfg.get('model', 'deepseek-chat'), ds_cfg['api_key'])

        # 智谱
        zp_cfg = llm_cfg.get('zhipu', {})
        if zp_cfg.get('enabled') and zp_cfg.get('api_key', ''):
            client.add_from_preset(zp_cfg.get('model', 'glm-4-flash'), zp_cfg['api_key'])

        # 硅基流动
        sf_cfg = llm_cfg.get('siliconflow', {})
        if sf_cfg.get('enabled') and sf_cfg.get('api_key', '').startswith('sk-'):
            client.add_from_preset(sf_cfg.get('model', 'silicon-deepseek-v3'), sf_cfg['api_key'])

        # 如果没有配置任何 key，使用免费预设提示
        if client.available_count == 0:
            self.logger.warning("⚠️  未配置任何 LLM API Key")
            self.logger.warning("💡 推荐免费方案:")
            self.logger.warning("   1. 智谱 glm-4-flash (免费): https://open.bigmodel.cn")
            self.logger.warning("   2. 硅基流动 (新用户免费额度): https://cloud.siliconflow.cn")
            self.logger.warning("   角色将使用本地台词库运行")

        return client

    def start(self):
        """启动所有监控模块 (CLI 模式，阻塞主线程)"""
        self.start_monitors()

        # CLI 主循环
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("收到退出信号...")
            self.stop()

    def start_monitors(self):
        """启动所有监控后台线程 (非阻塞，供 GUI 模式调用)"""
        self.logger.info("=" * 50)
        self.logger.info("  🛡️  AI 网络安全管家启动中...")
        self.logger.info("=" * 50)
        self.running = True

        # 连接设备
        if not self.device.connect():
            self.logger.warning("⚠️  设备未连接，将仅使用 Web Dashboard")

        # 启动安全扫描线程
        self._start_thread(self._scan_loop, "SecurityScanner")

        # 启动 AI 状态追踪
        if self.config.get('ai', {}).get('enabled', True):
            self._start_thread(self._ai_status_loop, "AIStatusTracker")

        # 启动 Web Dashboard
        if self.web:
            self._start_thread(self.web.run, "WebDashboard")

        # 启动系统托盘 (仅在非 GUI 模式)
        if self.tray:
            self._start_thread(self.tray.run, "SystemTray")

        # 初始状态推送
        self._push_state()

        self.logger.info("✅ 所有模块启动完成")
        self.logger.info("📟 查看 ESP32 屏幕确认连接状态")

    def stop(self):
        """停止所有模块"""
        self.running = False
        self.logger.info("正在关闭所有模块...")

        self.device.disconnect()
        if self.web:
            self.web.stop()
        if self.tray:
            self.tray.stop()

        self.logger.info("👋 AI 网络安全管家已关闭")

    def _start_thread(self, target, name):
        """启动守护线程"""
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        return t

    # ==================== 扫描循环 ====================

    def _scan_loop(self):
        """主扫描循环"""
        interval = self.config.get('security', {}).get('scan_interval', 5)

        while self.running:
            try:
                # 收集所有安全数据
                threats = []
                messages = []

                # 1. 网络安全扫描
                net_result = self.network.scan()
                suspicious_ips = net_result.get('suspicious_ips', 0)
                active_conns = net_result.get('active_connections', 0)
                net_status = net_result.get('status', 'normal')

                if net_status == 'under_attack':
                    threats.append(f"🚨 网络攻击检测! 可疑IP: {suspicious_ips}")
                    messages.append(f"检测到 {suspicious_ips} 个可疑IP连接")
                elif net_status == 'suspicious':
                    messages.append(f"网络异常: {suspicious_ips} 个可疑连接")

                # 2. 进程安全扫描
                proc_result = self.process.scan()
                suspicious_procs = proc_result.get('suspicious_count', 0)
                high_cpu_procs = proc_result.get('high_cpu_count', 0)

                if suspicious_procs > 0:
                    proc_names = proc_result.get('suspicious_names', [])
                    threats.append(f"⚠️ 检测到 {suspicious_procs} 个可疑进程: {', '.join(proc_names[:3])}")
                    messages.append(f"可疑进程: {', '.join(proc_names[:3])}")

                # 3. 防火墙检查 (每30秒)
                fw_result = self.firewall.check()
                firewall_on = fw_result.get('firewall_on', True)
                defender_on = fw_result.get('defender_on', True)

                if not firewall_on:
                    threats.append("🔴 防火墙已关闭!")
                    messages.append("警告: Windows 防火墙未启用")
                if not defender_on:
                    threats.append("🔴 Windows Defender 已关闭!")
                    messages.append("警告: 杀毒软件未运行")

                # 4. 系统资源
                import psutil
                cpu_percent = psutil.cpu_percent(interval=1)
                mem_percent = psutil.virtual_memory().percent
                cpu_warn = proc_result.get('cpu_percent', cpu_percent)

                if cpu_percent > self.config.get('security', {}).get('process', {}).get('cpu_threshold', 80):
                    messages.append(f"CPU 使用率过高: {cpu_percent:.1f}%")
                if mem_percent > self.config.get('security', {}).get('process', {}).get('mem_threshold', 80):
                    messages.append(f"内存使用率过高: {mem_percent:.1f}%")

                # 计算安全等级
                sec_level = self._calculate_security_level(
                    threats, suspicious_ips, suspicious_procs, firewall_on, defender_on
                )

                # 更新全局状态
                with self.state_lock:
                    self.state.update({
                        'sec_level': sec_level,
                        'threat_count': len(threats),
                        'blocked_count': fw_result.get('blocked_count', 0),
                        'last_threat': threats[-1] if threats else '',
                        'active_connections': active_conns,
                        'suspicious_ips': suspicious_ips,
                        'net_status': net_status,
                        'firewall_on': firewall_on,
                        'defender_on': defender_on,
                        'cpu_usage': cpu_percent,
                        'mem_usage': mem_percent,
                        'uptime': int(time.time() - psutil.boot_time()),
                        'messages': messages[-5:],  # 最多 5 条
                    })

                # 推送状态
                self._push_state()

                # 推送角色表情和台词
                self._push_character_commands(sec_level)

                # LLM 安全分析 (有威胁时)
                if sec_level in ('warning', 'danger') and self.character.is_llm_available:
                    llm_analysis = self.character.analyze_security_with_llm(
                        self.state
                    )
                    if llm_analysis:
                        self.logger.info(f"🧠 LLM分析: {llm_analysis}")
                        self.device.send_command({
                            "cmd": "say",
                            "text": llm_analysis[:40],
                        })

                # 如果是危险状态，额外通知
                if sec_level == 'danger':
                    self.device.send_alert(
                        f"安全威胁: {threats[-1] if threats else '未知威胁'}"
                    )

            except Exception as e:
                self.logger.error(f"扫描异常: {e}", exc_info=True)

            # 休眠到下次扫描
            for _ in range(interval):
                if not self.running:
                    break
                time.sleep(1)

    def _ai_status_loop(self):
        """AI 状态追踪循环"""
        interval = self.config.get('ai', {}).get('heartbeat_interval', 2)

        while self.running:
            try:
                status = self.ai_tracker.get_status()

                with self.state_lock:
                    self.state['ai_status'] = status.get('status', 'idle')
                    self.state['ai_task'] = status.get('task', '')
                    self.state['ai_progress'] = status.get('progress', 0)

                self._push_state()
            except Exception as e:
                self.logger.debug(f"AI 状态获取失败: {e}")

            for _ in range(interval):
                if not self.running:
                    break
                time.sleep(1)

    def _calculate_security_level(self, threats, suspicious_ips, suspicious_procs, firewall_on, defender_on):
        """综合计算安全等级"""
        if not firewall_on or not defender_on:
            return 'danger'
        if len(threats) >= 3 or suspicious_ips >= 5:
            return 'danger'
        if len(threats) >= 1 or suspicious_ips >= 2 or suspicious_procs >= 1:
            return 'warning'
        return 'safe'

    def _push_character_commands(self, sec_level: str):
        """推送角色表情和台词到设备"""
        try:
            # 安全等级变化时触发角色反应
            trigger = 'auto'
            if self._startup_phase:
                trigger = 'startup'
                self._startup_phase = False
            elif sec_level == 'danger' and self._last_sec_level != 'danger':
                trigger = 'threat'
            elif sec_level == 'safe' and self._last_sec_level == 'danger':
                trigger = 'cleared'

            self._last_sec_level = sec_level

            # 生成角色指令
            with self.state_lock:
                state_copy = self.state.copy()

            commands = self.character.generate_device_commands(state_copy)

            # 特殊触发
            if trigger == 'startup':
                commands = self.character.force_greeting()
            elif trigger == 'threat':
                threat_msg = state_copy.get('last_threat', '检测到威胁')
                commands = self.character.force_alert(threat_msg)

            # 发送指令
            for cmd in commands:
                self.device.send_command(cmd)

        except Exception as e:
            self.logger.debug(f"角色指令发送失败: {e}")

    def _push_state(self):
        """推送状态到设备"""
        with self.state_lock:
            state_copy = self.state.copy()
        self.device.send_update(state_copy)

    # 提供给 Web Dashboard 的接口
    def get_state(self) -> dict:
        with self.state_lock:
            return self.state.copy()

    def get_logs(self, lines: int = 50) -> list:
        log_file = self.config.get('logging', {}).get('file', 'guardian.log')
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
                return all_lines[-lines:]
        except FileNotFoundError:
            return []


# ==================== 入口 ====================

def check_admin_privileges(logger):
    """检查是否以管理员权限运行"""
    import ctypes
    try:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        is_admin = False

    if not is_admin:
        logger.warning("=" * 50)
        logger.warning("⚠️  未以管理员身份运行!")
        logger.warning("以下功能将受限:")
        logger.warning("  - 安全事件日志读取")
        logger.warning("  - Windows Defender 详细信息")
        logger.warning("  - 进程终止操作")
        logger.warning("  - 防火墙规则修改")
        logger.warning("  - 部分网络连接信息")
        logger.warning("")
        logger.warning("💡 右键启动程序 → \"以管理员身份运行\" 获取完整功能")
        logger.warning("=" * 50)


def main():
    parser = argparse.ArgumentParser(
        description='🛡️ AI 网络安全管家 - PC Agent',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python main.py                    # 默认启动
  python main.py --config my.yaml   # 使用自定义配置
  python main.py --no-tray          # 不启动系统托盘
  python main.py --no-device        # 不连接 ESP32 (仅 Web)
        """
    )
    parser.add_argument('--config', '-c', help='配置文件路径', default=None)
    parser.add_argument('--no-tray', action='store_true', help='禁用系统托盘')
    parser.add_argument('--no-device', action='store_true', help='禁用设备连接')
    parser.add_argument('--no-dashboard', action='store_true', help='禁用 Web Dashboard')
    parser.add_argument('--gui', action='store_true', help='启动桌面 GUI (PyQt5)')
    args = parser.parse_args()

    controller = GuardianController(config_path=args.config)

    if args.no_tray:
        controller.config['system_tray']['enabled'] = False
    if args.no_device:
        controller.config['device']['mode'] = 'none'
    if args.no_dashboard:
        controller.config['dashboard']['enabled'] = False

    # 管理员权限检查
    check_admin_privileges(controller.logger)

    # GUI 模式 — 统一单体应用，关闭 Web Dashboard 和 pystray
    if args.gui:
        if not HAS_GUI:
            print("❌ PyQt5 未安装。请运行: pip install PyQt5")
            sys.exit(1)
        controller.config['dashboard']['enabled'] = False
        controller.config['system_tray']['enabled'] = False
        controller.web = None
        controller.tray = None
        controller.start_monitors()
        exit_code = run_gui(controller, controller.logger)
        controller.stop()
        sys.exit(exit_code)

    # CLI 模式
    # 处理 Ctrl+C
    def signal_handler(sig, frame):
        controller.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    controller.start()


if __name__ == '__main__':
    main()
