"""
测试 GuardianController: 安全等级计算, 状态管理, 配置加载
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

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

    @pytest.mark.parametrize("kwargs,expected", [
        (dict(threats=[], suspicious_ips=0, suspicious_procs=0, firewall_on=False, defender_on=True), 'danger'),
        (dict(threats=[], suspicious_ips=0, suspicious_procs=0, firewall_on=True, defender_on=False), 'danger'),
        (dict(threats=['t1', 't2', 't3'], suspicious_ips=0, suspicious_procs=0, firewall_on=True, defender_on=True), 'danger'),
        (dict(threats=[], suspicious_ips=5, suspicious_procs=0, firewall_on=True, defender_on=True), 'danger'),
        (dict(threats=['t1'], suspicious_ips=0, suspicious_procs=0, firewall_on=True, defender_on=True), 'warning'),
        (dict(threats=[], suspicious_ips=0, suspicious_procs=1, firewall_on=True, defender_on=True), 'warning'),
        (dict(threats=[], suspicious_ips=0, suspicious_procs=0, firewall_on=True, defender_on=True), 'safe'),
    ])
    def test_security_level_calculation(self, kwargs, expected):
        result = self.controller._calculate_security_level(**kwargs)
        assert result == expected
