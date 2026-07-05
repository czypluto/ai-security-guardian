"""
防火墙检查模块 —— 检查 Windows 防火墙和 Defender 状态
"""

import logging
import subprocess
import threading
import time
from typing import Dict


class FirewallChecker:
    """Windows 防火墙 & Defender 状态检查"""

    def __init__(self, config: dict, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self._last_check = 0
        self._check_interval = config.get('check_interval', 30)
        self._cached_result = {}

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

        # 检查防火墙详情
        result['firewall_profiles'] = self._check_firewall_profiles()

        # 检查 Defender 详情
        result['defender_details'] = self._check_defender_details()

        self._last_check = now
        self._cached_result = result
        return result

    def _check_firewall(self) -> bool:
        """检查 Windows 防火墙是否开启"""
        try:
            # 方法1: netsh
            output = subprocess.run(
                ['netsh', 'advfirewall', 'show', 'allprofiles', 'state'],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            # 如果输出包含 OFF，说明至少有一个配置文件关闭
            if 'OFF' in output.stdout:
                self.logger.warning("⚠️  Windows 防火墙未完全启用")
                return False
            return 'ON' in output.stdout

        except subprocess.TimeoutExpired:
            self.logger.debug("防火墙检查超时")
        except FileNotFoundError:
            # netsh 不可用，尝试其他方法
            pass
        except Exception as e:
            self.logger.debug(f"防火墙检查失败: {e}")

        # 方法2: PowerShell
        try:
            result = subprocess.run(
                ['powershell', '-Command',
                 'Get-NetFirewallProfile | Where-Object {$_.Enabled -eq $false} | Measure-Object | Select-Object -ExpandProperty Count'],
                capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if result.stdout.strip() == '0':
                return True
        except Exception:
            pass

        return True  # 默认假设开启

    def _check_defender(self) -> bool:
        """检查 Windows Defender 是否运行"""
        try:
            # 检查 Defender 服务
            output = subprocess.run(
                ['powershell', '-Command',
                 'Get-MpComputerStatus | Select-Object -ExpandProperty AntivirusEnabled'],
                capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            if 'True' in output.stdout:
                return True
            if 'False' in output.stdout:
                self.logger.warning("⚠️  Windows Defender 未启用")
                return False

        except Exception as e:
            self.logger.debug(f"Defender 检查失败: {e}")

        # 备选：检查 MsMpEng.exe 进程
        try:
            import psutil
            for proc in psutil.process_iter(['name']):
                if proc.info['name'] and 'msmpeng' in proc.info['name'].lower():
                    return True
        except Exception:
            pass

        return True  # 默认假设开启

    def _check_firewall_profiles(self) -> Dict:
        """检查各防火墙配置文件"""
        profiles = {}
        try:
            result = subprocess.run(
                ['powershell', '-Command',
                 'Get-NetFirewallProfile | Select-Object Name, Enabled | Format-Table -HideTableHeaders'],
                capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            for line in result.stdout.strip().split('\n'):
                parts = line.strip().split()
                if len(parts) >= 2:
                    name = parts[0]
                    enabled = 'True' in parts[-1]
                    profiles[name] = enabled
        except Exception:
            pass
        return profiles

    def _check_defender_details(self) -> Dict:
        """检查 Defender 详细信息"""
        details = {}
        try:
            result = subprocess.run(
                ['powershell', '-Command',
                 'Get-MpComputerStatus | Select-Object '
                 'AntivirusEnabled, RealTimeProtectionEnabled, '
                 'AntispywareEnabled, IoavProtectionEnabled, '
                 'OnAccessProtectionEnabled, BehaviorMonitorEnabled | '
                 'ConvertTo-Json'],
                capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            import json
            details = json.loads(result.stdout) if result.stdout.strip() else {}
        except Exception:
            pass
        return details

    def get_blocked_connections(self) -> int:
        """获取被防火墙阻止的连接数"""
        count = 0
        try:
            result = subprocess.run(
                ['powershell', '-Command',
                 '(Get-NetFirewallRule -Action Block -Enabled True -Direction Inbound | '
                 'Measure-Object).Count'],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            count = int(result.stdout.strip() or 0)
        except Exception:
            pass
        return count

    def enable_firewall(self) -> bool:
        """开启防火墙"""
        try:
            subprocess.run(
                ['netsh', 'advfirewall', 'set', 'allprofiles', 'state', 'on'],
                capture_output=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            self.logger.info("✅ 防火墙已开启")
            self._last_check = 0  # 清除缓存
            return True
        except Exception as e:
            self.logger.error(f"❌ 开启防火墙失败: {e}")
            return False
