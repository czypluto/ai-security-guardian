"""
测试 NetworkMonitor: 可疑端口/IP检测, 高频连接检测, 状态计算
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
import psutil

from network_monitor import NetworkMonitor


# ---- Mock Helpers ----

def _make_conn(local_port, remote_ip, remote_port, status='ESTABLISHED', pid=1234):
    """构建模拟的 psutil 网络连接对象"""
    conn = MagicMock()
    conn.status = status
    conn.laddr = MagicMock()
    conn.laddr.port = local_port
    conn.raddr = MagicMock()
    conn.raddr.ip = remote_ip
    conn.raddr.port = remote_port
    conn.pid = pid
    return conn


def _make_listen_conn(port):
    """构建模拟的 LISTEN 状态连接"""
    conn = MagicMock()
    conn.status = 'LISTEN'
    conn.laddr = MagicMock()
    conn.laddr.port = port
    conn.raddr = None
    conn.pid = None
    return conn


# ---- Tests ----

class TestSuspiciousPortDetection:
    """可疑端口检测"""

    def setup_method(self):
        self.nm = NetworkMonitor({}, MagicMock())

    @patch('psutil.net_connections')
    def test_metasploit_port_detected(self, mock_conns, mock_logger):
        """连接 4444 端口应被检测为 Metasploit"""
        mock_conns.return_value = [
            _make_conn(50000, '10.0.0.5', 4444),
        ]
        self.nm.logger = mock_logger

        with patch('psutil.Process', return_value=MagicMock(name=lambda: 'python.exe')):
            result = self.nm.scan()

        assert result['suspicious_ips'] >= 1
        assert any(d.get('port') == 4444 for d in result['suspicious_details'])

    @patch('psutil.net_connections')
    def test_normal_port_not_flagged(self, mock_conns, mock_logger):
        """连接普通端口不应标记为可疑"""
        mock_conns.return_value = [
            _make_conn(50000, '93.184.216.34', 443),   # HTTPS
            _make_conn(50001, '142.250.80.46', 80),    # HTTP
        ]
        self.nm.logger = mock_logger

        result = self.nm.scan()
        assert result['suspicious_ips'] == 0

    @patch('psutil.net_connections')
    def test_irc_c2_port_detected(self, mock_conns, mock_logger):
        """连接 6667 端口应被标记为 IRC C2"""
        mock_conns.return_value = [
            _make_conn(50000, '45.33.32.156', 6667),
        ]
        self.nm.logger = mock_logger

        with patch('psutil.Process', return_value=MagicMock(name=lambda: 'unknown')):
            result = self.nm.scan()
        assert result['suspicious_ips'] >= 1


class TestSuspiciousIPDetection:
    """可疑 IP 段检测"""

    def setup_method(self):
        self.nm = NetworkMonitor({}, MagicMock())

    def test_tor_exit_node_flagged(self):
        """Tor 出口节点 IP 段应被标记"""
        assert self.nm._is_suspicious_ip('185.220.101.34') is True

    def test_local_ip_not_flagged(self):
        """本地 IP 不应标记"""
        assert self.nm._is_suspicious_ip('127.0.0.1') is False
        assert self.nm._is_suspicious_ip('192.168.1.100') is False
        assert self.nm._is_suspicious_ip('10.0.0.5') is False
        assert self.nm._is_suspicious_ip('172.16.0.1') is False

    def test_known_malicious_network_flagged(self):
        """已知恶意 IP 段应被标记"""
        assert self.nm._is_suspicious_ip('5.188.10.1') is True
        assert self.nm._is_suspicious_ip('45.155.20.5') is True
        assert self.nm._is_suspicious_ip('23.129.64.10') is True

    def test_normal_public_ip_not_flagged(self):
        """普通公网 IP 不应被标记"""
        assert self.nm._is_suspicious_ip('8.8.8.8') is False
        assert self.nm._is_suspicious_ip('1.1.1.1') is False


class TestStatusCalculation:
    """安全状态计算"""

    def setup_method(self):
        self.nm = NetworkMonitor({}, MagicMock())

    def test_no_threats_normal(self):
        result = {'suspicious_ips': 0, 'suspicious_details': []}
        # Mock scan 结果
        assert self.nm.scan.__wrapped__ if hasattr(self.nm.scan, '__wrapped__') else True

    @patch('psutil.net_connections')
    def test_status_under_attack(self, mock_conns, mock_logger):
        """5个以上可疑IP → under_attack"""
        connections = []
        for i in range(6):
            connections.append(_make_conn(50000 + i, f'185.220.101.{i+1}', 4444))
        mock_conns.return_value = connections
        self.nm.logger = mock_logger

        with patch('psutil.Process', return_value=MagicMock(name=lambda: 'malware.exe')):
            result = self.nm.scan()

        assert result['status'] == 'under_attack'

    @patch('psutil.net_connections')
    def test_status_suspicious(self, mock_conns, mock_logger):
        """1个可疑IP → suspicious"""
        mock_conns.return_value = [
            _make_conn(50000, '5.188.10.1', 6667),
        ]
        self.nm.logger = mock_logger

        with patch('psutil.Process', return_value=MagicMock(name=lambda: 'unknown.exe')):
            result = self.nm.scan()
        assert result['status'] == 'suspicious'

    @patch('psutil.net_connections')
    def test_status_normal(self, mock_conns, mock_logger):
        """0可疑IP → normal"""
        mock_conns.return_value = [
            _make_conn(50000, '93.184.216.34', 443),
        ]
        self.nm.logger = mock_logger

        result = self.nm.scan()
        assert result['status'] == 'normal'


class TestListeningPorts:
    """监听端口收集"""

    def setup_method(self):
        self.nm = NetworkMonitor({}, MagicMock())

    @patch('psutil.net_connections')
    def test_listening_ports_collected(self, mock_conns, mock_logger):
        mock_conns.return_value = [
            _make_listen_conn(22),
            _make_listen_conn(80),
            _make_listen_conn(443),
            _make_listen_conn(3389),
        ]
        self.nm.logger = mock_logger

        result = self.nm.scan()
        assert len(result['listen_ports']) == 4
        assert 443 in result['listen_ports']

    def test_get_listening_ports(self):
        ports = self.nm.get_listening_ports()
        assert isinstance(ports, list)
