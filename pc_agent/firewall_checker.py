"""
防火墙检查模块 —— 检查 Windows 防火墙和 Defender 状态

v1.1: 改进超时处理, 添加检查失败降级逻辑, 避免阻塞主扫描循环
"""

import logging
import subprocess
import time
from typing import Dict, Optional

# 全局超时常量
SHORT_TIMEOUT = 8    # netsh 等快速命令
LONG_TIMEOUT = 12    # PowerShell 命令


def _run_powershell(cmd: str, timeout: int = LONG_TIMEOUT) -> Optional[str]:
    """安全执行 PowerShell 命令, 统一超时和异常处理"""
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-Command', cmd],
            capture_output=True, text=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
            encoding="utf-8", errors="replace",
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except subprocess.TimeoutExpired:
        return None
    except FileNotFoundError:
        return None
    except Exception:
        return None


class FirewallChecker:
    """Windows 防火墙 & Defender 状态检查"""

    def __init__(self, config: dict, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self._last_check = 0
        self._check_interval = config.get('check_interval', 30)
        self._cached_result = {}
        self._consecutive_failures = 0

    def check(self) -> Dict:
        """检查防火墙和杀毒状态 (带缓存)"""
        now = time.time()
        if now - self._last_check < self._check_interval and self._cached_result:
            return self._cached_result

        result = {
            'firewall_on': self._check_firewall(),
            'defender_on': self._check_defender(),
            'firewall_profiles': {},
            'defender_details': {},
            'blocked_count': 0,
        }

        # 仅在基础检查成功时获取详情
        if result['firewall_on']:
            result['firewall_profiles'] = self._check_firewall_profiles()
        if result['defender_on']:
            result['defender_details'] = self._check_defender_details()

        self._last_check = now
        self._cached_result = result
        self._consecutive_failures = 0
        return result

    def _check_firewall(self) -> bool:
        """检查 Windows 防火墙是否开启 (多级降级)"""
        # 方法1: netsh (最快, 最常见)
        try:
            output = subprocess.run(
                ['netsh', 'advfirewall', 'show', 'allprofiles', 'state'],
                capture_output=True, text=True, timeout=SHORT_TIMEOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
                encoding="utf-8", errors="replace",
            )
            if output.returncode == 0:
                # 如果输出包含 OFF，说明至少有一个配置文件关闭
                if 'OFF' in output.stdout:
                    self.logger.warning("⚠️  Windows 防火墙未完全启用")
                    return False
                if 'ON' in output.stdout:
                    return True
        except subprocess.TimeoutExpired:
            self.logger.debug("netsh 防火墙检查超时, 尝试 PowerShell...")
        except FileNotFoundError:
            self.logger.debug("netsh 不可用, 尝试 PowerShell...")
        except Exception as e:
            self.logger.debug(f"netsh 防火墙检查失败: {e}")

        # 方法2: PowerShell
        ps_result = _run_powershell(
            'Get-NetFirewallProfile | Where-Object {$_.Enabled -eq $false} | Measure-Object | Select-Object -ExpandProperty Count'
        )
        if ps_result is not None:
            return ps_result == '0'

        # 方法3: 检查防火墙服务
        try:
            output = subprocess.run(
                ['sc', 'query', 'mpssvc'],
                capture_output=True, text=True, timeout=SHORT_TIMEOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
                encoding="utf-8", errors="replace",
            )
            if 'RUNNING' in output.stdout:
                return True
        except Exception:
            pass

        self._consecutive_failures += 1
        # 连续失败后使用缓存值
        if self._consecutive_failures > 3 and self._cached_result:
            self.logger.warning(f"防火墙检查连续失败 {self._consecutive_failures} 次, 使用缓存值")
            return self._cached_result.get('firewall_on', True)

        return True  # 默认假设开启

    def _check_defender(self) -> bool:
        """检查 Windows Defender 是否运行 (多级降级)"""
        # 方法1: PowerShell Get-MpComputerStatus (最可靠)
        ps_result = _run_powershell(
            'Get-MpComputerStatus | Select-Object -ExpandProperty AntivirusEnabled'
        )
        if ps_result is not None:
            if 'True' in ps_result:
                return True
            if 'False' in ps_result:
                self.logger.warning("⚠️  Windows Defender 未启用")
                return False

        # 方法2: 检查 MsMpEng.exe 进程
        try:
            import psutil
            for proc in psutil.process_iter(['name']):
                try:
                    if proc.info['name'] and 'msmpeng' in proc.info['name'].lower():
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            self.logger.debug(f"Defender 进程检查失败: {e}")

        # 方法3: 检查 WinDefend 服务
        try:
            output = subprocess.run(
                ['sc', 'query', 'WinDefend'],
                capture_output=True, text=True, timeout=SHORT_TIMEOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
                encoding="utf-8", errors="replace",
            )
            if 'RUNNING' in output.stdout:
                return True
        except Exception:
            pass

        self._consecutive_failures += 1
        if self._consecutive_failures > 3 and self._cached_result:
            return self._cached_result.get('defender_on', True)

        return True  # 默认假设开启

    def _check_firewall_profiles(self) -> Dict:
        """检查各防火墙配置文件"""
        ps_result = _run_powershell(
            'Get-NetFirewallProfile | Select-Object Name, Enabled | Format-Table -HideTableHeaders'
        )
        profiles = {}
        if ps_result:
            for line in ps_result.split('\n'):
                parts = line.strip().split()
                if len(parts) >= 2:
                    name = parts[0]
                    enabled = 'True' in parts[-1]
                    profiles[name] = enabled
        return profiles

    def _check_defender_details(self) -> Dict:
        """检查 Defender 详细信息"""
        ps_result = _run_powershell(
            'Get-MpComputerStatus | Select-Object '
            'AntivirusEnabled, RealTimeProtectionEnabled, '
            'AntispywareEnabled, IoavProtectionEnabled, '
            'OnAccessProtectionEnabled, BehaviorMonitorEnabled | '
            'ConvertTo-Json'
        )
        if ps_result:
            try:
                import json
                return json.loads(ps_result)
            except json.JSONDecodeError:
                pass
        return {}

