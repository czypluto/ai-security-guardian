"""
测试 GuardianController: 安全等级计算, 状态管理, 配置加载
"""

import sys
import os
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

# 将 pc_agent 加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'pc_agent'))

from main import GuardianController


class TestSecurityLevelCalculation:
    """安全等级计算逻辑"""

    def setup_method(self):
        """创建一个最小化的 controller (不启动任何模块)"""
        with patch('main.DeviceBridge'), \
             patch('main.AIStatusTracker'), \
             patch('main.SecurityMonitor'), \
             patch('main.NetworkMonitor'), \
             patch('main.ProcessMonitor'), \
             patch('main.FirewallChecker'), \
             patch('main.MultiLLMClient'), \
             patch('main.CharacterManager'), \
             patch('main.setup_logging', return_value=MagicMock()), \
             patch('main.HAS_TRAY', False), \
             patch('main.HAS_GUI', False), \
             patch('builtins.open', create=True), \
             patch('yaml.safe_load', return_value={
                 'device': {'mode': 'none'},
                 'security': {
                     'scan_interval': 5,
                     'network': {},
                     'process': {'cpu_threshold': 80, 'mem_threshold': 80},
                     'firewall': {},
                 },
                 'ai': {'enabled': False},
                 'system_tray': {'enabled': False},
                 'llm': {'enabled': False},
                 'character': {},
                 'logging': {'level': 'WARNING'},
             }):
            self.controller = GuardianController()

    def test_danger_when_firewall_off(self):
        result = self.controller._calculate_security_level(
            threats=[], suspicious_ips=0, suspicious_procs=0,
            firewall_on=False, defender_on=True
        )
        assert result == 'danger'

    def test_danger_when_defender_off(self):
        result = self.controller._calculate_security_level(
            threats=[], suspicious_ips=0, suspicious_procs=0,
            firewall_on=True, defender_on=False
        )
        assert result == 'danger'

    def test_danger_with_3_plus_threats(self):
        result = self.controller._calculate_security_level(
            threats=['t1', 't2', 't3'], suspicious_ips=0, suspicious_procs=0,
            firewall_on=True, defender_on=True
        )
        assert result == 'danger'

    def test_danger_with_5_plus_suspicious_ips(self):
        result = self.controller._calculate_security_level(
            threats=[], suspicious_ips=5, suspicious_procs=0,
            firewall_on=True, defender_on=True
        )
        assert result == 'danger'

    def test_warning_with_1_threat(self):
        result = self.controller._calculate_security_level(
            threats=['t1'], suspicious_ips=0, suspicious_procs=0,
            firewall_on=True, defender_on=True
        )
        assert result == 'warning'

    def test_warning_with_suspicious_proc(self):
        result = self.controller._calculate_security_level(
            threats=[], suspicious_ips=0, suspicious_procs=1,
            firewall_on=True, defender_on=True
        )
        assert result == 'warning'

    def test_safe_when_all_clear(self):
        result = self.controller._calculate_security_level(
            threats=[], suspicious_ips=0, suspicious_procs=0,
            firewall_on=True, defender_on=True
        )
        assert result == 'safe'
