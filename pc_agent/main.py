#!/usr/bin/env python3
"""
AI 网络安全管家 - PC Agent 主程序
AI Network Security Guardian - Main Entry Point

启动后自动:
 1. 监控 Windows 安全状态
 2. 检测网络威胁
 3. 扫描可疑进程
 4. 检查防火墙/杀毒状态
 5. 将状态推送到 ESP32 设备
"""

import argparse
import logging
import signal
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import yaml

# 同目录模块要同时支持两种运行方式：
#   * 当脚本:  python pc_agent/main.py          -> __package__ 为空，走扁平导入
#   * 当包:    poetry 的 guardian-pc 入口         -> __package__ == "pc_agent"，走相对导入
#
# 以前只有扁平导入，于是 `import pc_agent.main` 直接 ModuleNotFoundError:
# No module named 'ai_status'，pyproject 里声明的 guardian-pc 入口根本不可用。
# 不能靠往 sys.path 里塞 pc_agent/ 来统一 —— 那样 `ai_status` 与
# `pc_agent.ai_status` 会成为两个不同的模块对象，跨模块 isinstance 会莫名失败。
if __package__:
    from .ai_status import AIStatusTracker
    from .character_manager import CharacterManager
    from .device_bridge import DeviceBridge
    from .firewall_checker import FirewallChecker
    from .llm_client import MultiLLMClient, Provider
    from .network_monitor import NetworkMonitor
    from .process_monitor import ProcessMonitor
    from .security_monitor import SecurityMonitor
else:
    from ai_status import AIStatusTracker
    from character_manager import CharacterManager
    from device_bridge import DeviceBridge
    from firewall_checker import FirewallChecker
    from llm_client import MultiLLMClient, Provider
    from network_monitor import NetworkMonitor
    from process_monitor import ProcessMonitor
    from security_monitor import SecurityMonitor

# agent/llm.py 集成
sys.path.insert(0, str(Path(__file__).parent.parent))
from agent.config import AgentConfig  # noqa: E402

# 可选模块
try:
    if __package__:
        from .system_tray import SystemTrayApp
    else:
        from system_tray import SystemTrayApp
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

try:
    if __package__:
        from .desktop_gui import HAS_PYQT5, run_gui
    else:
        from desktop_gui import HAS_PYQT5, run_gui
    HAS_GUI = HAS_PYQT5
except ImportError:
    HAS_GUI = False

# 日志
def setup_logging(config: dict):
    """配置日志系统。

    修掉的两个问题：
      1. `logging.file` 原先是**相对路径**，落点取决于从哪个目录启动 ——
         所以磁盘上会同时出现 `./guardian.log` 和 `pc_agent/guardian.log`。
         现在锚定到项目根。
      2. `max_size_mb` / `backup_count` 写在 config.yaml 里，但原实现用的是
         不会轮转的 `FileHandler`，**这两个配置项完全没有被使用** ——
         日志会无限增长。现在改用 `RotatingFileHandler`。

    另外把日志级别的解析做稳：yaml 里写了非法值（比如 `level: verbose`）时
    原实现会 `getattr(logging, 'verbose')` 抛 AttributeError，现在退回 INFO。
    """
    try:
        import colorlog
        _has_colorlog = True
    except ImportError:
        _has_colorlog = False

    log_config = config.get('logging', {}) or {}
    level = getattr(logging, str(log_config.get('level', 'INFO')).upper(), logging.INFO)

    # 绝对路径：`Path(root) / 绝对路径` 在 pathlib 里会保留右边，所以用户配绝对路径也不受影响
    log_file = str(Path(__file__).parent.parent / log_config.get('file', 'guardian.log'))
    max_bytes = int(log_config.get('max_size_mb', 10)) * 1024 * 1024
    backup_count = int(log_config.get('backup_count', 3))
    try:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001 - 建目录失败就让 FileHandler 去报错
        pass

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

    # 文件 handler —— 轮转由 max_size_mb / backup_count 控制（原来这两个配置是哑的）
    file_handler = RotatingFileHandler(
        log_file, maxBytes=max_bytes, backupCount=backup_count, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    ))

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    return logging.getLogger('Guardian')


# 主控制器
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
        """初始化多模型 LLM 客户端 (使用 agent/llm.py 的 LLMRouter)"""
        llm_cfg = self.config.get('llm', {})
        if not llm_cfg.get('enabled', True):
            self.logger.info("LLM 功能已禁用")
            return MultiLLMClient([], self.logger)

        # 使用 AgentConfig 解析配置 (支持 ${ENV_VAR} 解析)
        config_path = Path(__file__).parent / 'config.yaml'
        try:
            agent_cfg = AgentConfig.from_config_file(str(config_path))
        except Exception as e:
            self.logger.warning(f"AgentConfig 解析失败: {e}，回退到手动模式")
            agent_cfg = None

        client = MultiLLMClient([], self.logger)

        if agent_cfg and agent_cfg.providers:
            # 从 AgentConfig 直接注入已配置的 providers
            if __package__:
                from .llm_client import LLMConfig as LLCfg
            else:
                from llm_client import LLMConfig as LLCfg

            # 保留供应商身份，而不是一律标成 CUSTOM —— 界面上要显示用的哪家
            by_name = {
                "deepseek": Provider.DEEPSEEK,
                "zhipu": Provider.ZHIPU,
                "siliconflow": Provider.SILICONFLOW,
            }
            for p in agent_cfg.providers:
                client.add_provider(LLCfg(
                    provider=by_name.get(p.name, Provider.CUSTOM),
                    api_key=p.api_key,
                    model=p.model,
                    base_url=p.base_url,
                    max_tokens=p.max_tokens,
                    temperature=p.temperature,
                    timeout=p.timeout,
                ))
        else:
            # 回退: 手动从 config 构建
            ds_cfg = llm_cfg.get('deepseek', {})
            if ds_cfg.get('enabled') and ds_cfg.get('api_key', '').startswith('sk-'):
                client.add_from_preset(ds_cfg.get('model', 'deepseek-chat'), ds_cfg['api_key'])

            zp_cfg = llm_cfg.get('zhipu', {})
            if zp_cfg.get('enabled') and zp_cfg.get('api_key', ''):
                client.add_from_preset(zp_cfg.get('model', 'glm-4-flash'), zp_cfg['api_key'])

            sf_cfg = llm_cfg.get('siliconflow', {})
            if sf_cfg.get('enabled') and sf_cfg.get('api_key', '').startswith('sk-'):
                client.add_from_preset(sf_cfg.get('model', 'silicon-deepseek-v3'), sf_cfg['api_key'])

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

        # ---- 启动前自审计 — 先保证自己没被篡改，再保护别人 ----
        self._run_startup_integrity_check()

        # 连接设备
        if not self.device.connect():
            self.logger.warning("⚠️  设备未连接，将使用桌面 GUI 监控")

        # 启动安全扫描线程
        self._start_thread(self._scan_loop, "SecurityScanner")

        # 启动 AI 状态追踪
        if self.config.get('ai', {}).get('enabled', True):
            self._start_thread(self._ai_status_loop, "AIStatusTracker")

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
        if self.tray:
            self.tray.stop()

        self.logger.info("👋 AI 网络安全管家已关闭")

    def _start_thread(self, target, name):
        """启动守护线程"""
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        return t

    # 扫描循环

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

                if suspicious_procs > 0:
                    proc_names = proc_result.get('suspicious_names', [])
                    threats.append(f"⚠️ 检测到 {suspicious_procs} 个可疑进程: {', '.join(proc_names[:3])}")
                    messages.append(f"可疑进程: {', '.join(proc_names[:3])}")

                # 高内存进程（ProcessMonitor.mem_threshold 此前是个哑配置）
                high_mem = proc_result.get('high_mem_count', 0)
                if high_mem > 0:
                    mem_names = [d['name'] for d in
                                 proc_result.get('high_mem_details', [])[:3]]
                    messages.append(f"高内存进程 {high_mem} 个: {', '.join(mem_names)}")

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

                # 4. Windows 安全事件日志 (EventLog)
                #
                # SecurityMonitor 此前一直在 __init__ 里被实例化却**从不调用** ——
                # 这一段是它第一次真正进入主链路。读事件日志比其它检查重得多，
                # 不能跟着 5s 的主循环跑，因此单独节流到 60s 一次。
                now_ts = time.time()
                if now_ts - getattr(self, '_last_sec_log_check', 0) >= 60:
                    self._last_sec_log_check = now_ts
                    try:
                        sec = self.security.get_summary()
                    except Exception as e:
                        self.logger.debug(f"安全事件读取跳过: {e}")
                        sec = {}
                    failed_logins = sec.get('failed_logins', 0)
                    new_users = sec.get('new_users', 0)
                    if failed_logins > 0:
                        messages.append(f"安全日志: 登录失败 {failed_logins} 次")
                    if failed_logins > 5:
                        threats.append(f"🚨 大量登录失败 ({failed_logins} 次)")
                    if new_users > 0:
                        threats.append(f"🚨 检测到新增用户账户 ({new_users} 个)")

                # 5. 系统资源
                import psutil
                cpu_percent = psutil.cpu_percent(interval=1)
                mem_percent = psutil.virtual_memory().percent

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

    def _run_startup_integrity_check(self):
        """
        启动前快速自审计 — 确保 Guardian 自身未被篡改。
        只执行关键检查 (~1s)，不影响启动速度。
        发现问题时记录严重警告但不阻止启动（用户可能正在调试）。
        """
        try:
            from agent.self_audit import SelfAuditor
            auditor = SelfAuditor()
            result = auditor.quick_check()

            if result["ok"]:
                self.logger.info("🔒 启动自检通过 — 系统完整性已确认")
            else:
                issues = result.get("issues", [])
                critical = [i for i in issues if i.get("severity") == "CRITICAL"]
                high = [i for i in issues if i.get("severity") == "HIGH"]

                self.logger.warning("=" * 50)
                self.logger.warning("⚠️  启动自检发现问题!")
                self.logger.warning(f"   CRITICAL: {len(critical)}  HIGH: {len(high)}")
                for issue in critical[:5]:
                    self.logger.warning(f"   🔴 {issue.get('issue', str(issue))}")
                for issue in high[:5]:
                    self.logger.warning(f"   🟡 {issue.get('issue', str(issue))}")
                self.logger.warning("")
                self.logger.warning("💡 运行完整审计: python agent/self_audit.py --full")
                if critical:
                    self.logger.warning("🚨 检测到严重问题! 建议:")
                    self.logger.warning("   1. 运行 git diff 检查代码变更")
                    self.logger.warning("   2. 运行 pip list 检查可疑包")
                    self.logger.warning("   3. 如 API Key 泄露，立即重置!")
                self.logger.warning("=" * 50)

        except ImportError as e:
            self.logger.debug("自审计模块不可用: %s", e)
        except Exception as e:
            self.logger.warning("启动自检执行失败: %s", e)

    # 提供给 GUI 的接口
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


# 入口
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


def startup_lockdown_check(config: dict) -> list:
    """启动熔断：配置开启时，自检发现 CRITICAL 问题就拒绝启动。

    返回致命问题列表；空列表 = 可以继续启动。

    默认**关闭**（`agent.lockdown_on_critical`）。不开的时候直接返回，不会额外
    跑一次自检 —— 常规告警由 `_run_startup_integrity_check` 负责，那条路径
    只提示、不阻止启动（用户可能正在调试）。

    「熔断」这个词以前只出现在 README 里，代码里没有任何实现。现在是真实的了。
    """
    try:
        if not (config.get('agent') or {}).get('lockdown_on_critical', False):
            return []
    except AttributeError:
        return []

    try:
        from agent.self_audit import SelfAuditor
    except ImportError:
        return []

    try:
        result = SelfAuditor().quick_check()
    except Exception:
        return []   # 自检本身跑不起来，不该成为拒绝启动的理由

    return [i for i in result.get("issues", []) if i.get("severity") == "CRITICAL"]


def main():
    parser = argparse.ArgumentParser(
        description='🛡️ AI 网络安全管家 - PC Agent',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python main.py                    # 默认启动
  python main.py --config my.yaml   # 使用自定义配置
  python main.py --no-tray          # 不启动系统托盘
  python main.py --no-device        # 不连接 ESP32
        """
    )
    parser.add_argument('--config', '-c', help='配置文件路径', default=None)
    parser.add_argument('--no-tray', action='store_true', help='禁用系统托盘')
    parser.add_argument('--no-device', action='store_true', help='禁用设备连接')
    parser.add_argument('--gui', action='store_true', help='启动桌面 GUI (PyQt5)')
    args = parser.parse_args()

    controller = GuardianController(config_path=args.config)

    if args.no_tray:
        controller.config['system_tray']['enabled'] = False
    if args.no_device:
        controller.config['device']['mode'] = 'none'

    # 管理员权限检查
    check_admin_privileges(controller.logger)

    # 启动熔断（opt-in）：开了 agent.lockdown_on_critical 就在这里挡住
    fatal = startup_lockdown_check(controller.config)
    if fatal:
        print()
        print("  \033[31m🚫 启动已中止：自检发现严重问题，且已开启熔断\033[0m")
        for issue in fatal[:8]:
            print(f"     🔴 {issue.get('issue') or issue.get('file') or issue}")
        print()
        print("     确认无误后：把配置里的 agent.lockdown_on_critical 改回 false；")
        print("     若只是改过代码导致基线过期，运行 python generate_integrity_manifest.py")
        print("     重建基线即可。")
        print()
        sys.exit(2)

    # GUI 模式 — 统一单体应用，关闭 pystray
    if args.gui:
        if not HAS_GUI:
            print("❌ PyQt5 未安装。请运行: pip install PyQt5")
            sys.exit(1)
        controller.config['system_tray']['enabled'] = False
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


