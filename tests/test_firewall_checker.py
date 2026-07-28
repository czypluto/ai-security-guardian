"""
测试 FirewallChecker: 超时处理, 多级降级, 缓存逻辑
"""

import time
import pytest
import subprocess
from unittest.mock import MagicMock, patch, PropertyMock

from firewall_checker import FirewallChecker, _run_powershell


class TestPowerShellRunner:
    """_run_powershell 工具函数"""

    @patch('subprocess.run')
    def test_successful_call(self, mock_run, mock_logger):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = 'True\n'
        mock_run.return_value = mock_result

        result = _run_powershell('Get-Something')
        assert result == 'True'

    @patch('subprocess.run')
    def test_timeout_returns_none(self, mock_run, mock_logger):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='test', timeout=5)

        result = _run_powershell('Get-Something', timeout=5)
        assert result is None

    @patch('subprocess.run')
    def test_nonzero_returncode_returns_none(self, mock_run, mock_logger):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = 'Error'
        mock_run.return_value = mock_result

        result = _run_powershell('Get-Something')
        assert result is None

    @patch('subprocess.run')
    def test_filenotfound_returns_none(self, mock_run, mock_logger):
        mock_run.side_effect = FileNotFoundError('powershell not found')

        result = _run_powershell('Get-Something')
        assert result is None


class TestCaching:
    """缓存逻辑"""

    def setup_method(self):
        self.fc = FirewallChecker({}, MagicMock())

    def test_cache_returns_same_result_within_interval(self):
        self.fc._last_check = time.time()
        self.fc._check_interval = 60
        self.fc._cached_result = {
            'firewall_on': True,
            'defender_on': True,
            'firewall_profiles': {'Public': True},
            'defender_details': {'RealTimeProtectionEnabled': True},
            'blocked_count': 10,
        }

        result = self.fc.check()
        assert result['firewall_on'] is True
        assert result['blocked_count'] == 10

    def test_cache_expired_rechecks(self):
        self.fc._last_check = time.time() - 120  # 2分钟前
        self.fc._check_interval = 30
        self.fc._cached_result = {'firewall_on': False}

        with patch.object(self.fc, '_check_firewall', return_value=True), \
             patch.object(self.fc, '_check_defender', return_value=True), \
             patch.object(self.fc, '_check_firewall_profiles', return_value={}), \
             patch.object(self.fc, '_check_defender_details', return_value={}):
            result = self.fc.check()
            # 缓存过期, 重新检查
            assert result['firewall_on'] is True


class TestFallbackLogic:
    """多级降级逻辑"""

    def setup_method(self):
        self.fc = FirewallChecker({}, MagicMock())

    def test_consecutive_failures_use_cache(self):
        """连续失败后使用缓存值"""
        self.fc._cached_result = {'firewall_on': False, 'defender_on': True}
        self.fc._consecutive_failures = 5

        with patch.object(self.fc, '_check_firewall', return_value=True):
            # check() 会重置 _consecutive_failures
            self.fc.check()
            assert self.fc._consecutive_failures == 0

    @patch('subprocess.run')
    def test_netsh_timeout_falls_back_to_powershell(self, mock_run, mock_logger):
        """netsh 超时 → PowerShell 降级"""
        self.fc.logger = mock_logger

        # netsh 超时
        mock_run.side_effect = [
            subprocess.TimeoutExpired(cmd='netsh', timeout=8),  # netsh
            MagicMock(returncode=0, stdout='0'),                 # PowerShell
        ]

        with patch('firewall_checker._run_powershell', return_value='0'):
            result = self.fc._check_firewall()
            assert result is True

    @patch('subprocess.run')
    def test_all_methods_fail_default_true(self, mock_run, mock_logger):
        """所有方法都失败时默认返回 True"""
        self.fc.logger = mock_logger
        mock_run.side_effect = Exception("一切失败")

        result = self.fc._check_firewall()
        assert result is True  # 安全默认值
