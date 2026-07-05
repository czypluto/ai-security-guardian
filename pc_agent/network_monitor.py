"""
网络监控模块 —— 检测可疑连接和网络异常
"""

import logging
import threading
from collections import defaultdict
from typing import Dict, List, Set

import psutil


class NetworkMonitor:
    """网络连接监控和威胁检测"""

    # 已知恶意端口
    MALICIOUS_PORTS = {
        4444: 'Metasploit Meterpreter',
        1337: '常见后门',
        31337: 'Back Orifice',
        6666: 'IRC C2',
        6667: 'IRC C2',
        6697: 'IRC SSL',
        8080: 'HTTP代理/隧道',
        8888: '常见代理',
        9001: 'Tor OR',
        9030: 'Tor',
        9050: 'Tor SOCKS',
        9150: 'Tor Browser',
        4443: 'Metasploit',
        5555: 'Android ADB',
        2323: 'Telnet替代',
        3389: 'RDP (对外)',
        5900: 'VNC',
        6379: 'Redis (未授权)',
        27017: 'MongoDB (未授权)',
    }

    # 已知恶意 IP 段 (简化版)
    SUSPICIOUS_NETWORKS = [
        '5.188.',  # 常见攻击IP段
        '45.155.',
        '185.220.',  # Tor 出口节点
        '23.129.',
    ]

    def __init__(self, config: dict, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self._suspicious_ports = set(config.get('suspicious_ports', []))
        self._suspicious_ports.update(self.MALICIOUS_PORTS.keys())
        self._conn_history = defaultdict(int)  # IP → 连接次数
        self._blocked_ips: Set[str] = set()

    def scan(self) -> Dict:
        """扫描网络连接"""
        result = {
            'active_connections': 0,
            'suspicious_ips': 0,
            'suspicious_details': [],
            'blocked_count': len(self._blocked_ips),
            'status': 'normal',
            'listen_ports': [],
            'established_connections': [],
        }

        try:
            connections = psutil.net_connections(kind='inet')

            for conn in connections:
                result['active_connections'] += 1

                if conn.status == 'LISTEN':
                    if conn.laddr.port:
                        result['listen_ports'].append(conn.laddr.port)

                if conn.status == 'ESTABLISHED':
                    remote_ip = conn.raddr.ip if conn.raddr else ''
                    remote_port = conn.raddr.port if conn.raddr else 0
                    local_port = conn.laddr.port if conn.laddr else 0

                    result['established_connections'].append({
                        'local_port': local_port,
                        'remote': f"{remote_ip}:{remote_port}",
                        'pid': conn.pid,
                    })

                    # 检查可疑端口
                    if remote_port in self._suspicious_ports:
                        proc_name = self._get_process_name(conn.pid)
                        self._conn_history[remote_ip] += 1

                        detail = {
                            'ip': remote_ip,
                            'port': remote_port,
                            'reason': self.MALICIOUS_PORTS.get(remote_port, '可疑端口'),
                            'process': proc_name,
                            'severity': 'high',
                        }
                        result['suspicious_details'].append(detail)
                        result['suspicious_ips'] += 1

                    # 检查可疑 IP 段
                    if self._is_suspicious_ip(remote_ip):
                        self._conn_history[remote_ip] += 1
                        if remote_ip not in [d['ip'] for d in result['suspicious_details']]:
                            result['suspicious_details'].append({
                                'ip': remote_ip,
                                'port': remote_port,
                                'reason': '已知恶意IP段',
                                'process': self._get_process_name(conn.pid),
                                'severity': 'high',
                            })
                            result['suspicious_ips'] += 1

                # 统计可疑连接历史
                high_freq_ips = [
                    ip for ip, count in self._conn_history.items()
                    if count > 50  # 短时间大量连接
                ]
                for ip in high_freq_ips:
                    if ip not in [d['ip'] for d in result['suspicious_details']]:
                        result['suspicious_details'].append({
                            'ip': ip,
                            'port': 0,
                            'reason': f'高频连接 ({self._conn_history[ip]}次)',
                            'severity': 'medium',
                        })
                        result['suspicious_ips'] += 1

        except psutil.AccessDenied:
            self.logger.debug("部分网络信息需要管理员权限")
        except Exception as e:
            self.logger.error(f"网络扫描异常: {e}")

        # 计算网络状态
        if result['suspicious_ips'] >= 5:
            result['status'] = 'under_attack'
        elif result['suspicious_ips'] >= 1:
            result['status'] = 'suspicious'
        else:
            result['status'] = 'normal'

        return result

    def _get_process_name(self, pid: int) -> str:
        """获取进程名"""
        try:
            if pid:
                proc = psutil.Process(pid)
                return proc.name()
        except Exception:
            pass
        return 'unknown'

    def _is_suspicious_ip(self, ip: str) -> bool:
        """检查 IP 是否可疑"""
        if not ip or ip.startswith('127.') or ip.startswith('192.168.') or ip.startswith('10.') or ip.startswith('172.'):
            return False
        for prefix in self.SUSPICIOUS_NETWORKS:
            if ip.startswith(prefix):
                return True
        return False

    def get_listening_ports(self) -> List[int]:
        """获取所有监听端口"""
        ports = []
        try:
            for conn in psutil.net_connections(kind='inet'):
                if conn.status == 'LISTEN' and conn.laddr.port:
                    ports.append(conn.laddr.port)
        except Exception:
            pass
        return sorted(set(ports))

    def reset_history(self):
        """重置连接历史"""
        self._conn_history.clear()
        self._blocked_ips.clear()
