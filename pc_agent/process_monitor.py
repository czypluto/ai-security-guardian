"""
进程监控模块 —— 检测可疑进程和异常行为
"""

import logging
from typing import Dict, List

import psutil


class ProcessMonitor:
    """进程行为监控"""

    # 已知黑客工具特征名
    MALICIOUS_NAMES = {
        'mimikatz', 'mimikatz.exe', 'mimidrv.sys',
        'metasploit', 'msfvenom', 'msfconsole',
        'cobalt', 'beacon', 'cobaltstrike',
        'nc.exe', 'nc64.exe', 'netcat',
        'nmap', 'zenmap',
        'psexec', 'psexesvc',
        'procdump', 'procexp',
        'wireshark', 'tshark',
        'hydra', 'medusa',
        'john', 'hashcat',
        'sqlmap',
        'burpsuite', 'burp',
        ' Responder', 'responder',
        'empire', 'powersploit',
        'certutil.exe',  # 用于下载恶意文件时
    }

    def __init__(self, config: dict, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self._suspicious_names = set(config.get('suspicious_names', []))
        self._suspicious_names.update(self.MALICIOUS_NAMES)
        self.cpu_threshold = config.get('cpu_threshold', 80)
        self.mem_threshold = config.get('mem_threshold', 80)

    def scan(self) -> Dict:
        """扫描可疑进程"""
        result = {
            'total_processes': 0,
            'suspicious_count': 0,
            'suspicious_names': [],
            'suspicious_details': [],
            'high_cpu_count': 0,
            'high_cpu_details': [],
            'cpu_percent': psutil.cpu_percent(interval=0.5),
        }

        try:
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent',
                                              'exe', 'cmdline', 'create_time']):
                try:
                    info = proc.info
                    result['total_processes'] += 1
                    proc_name = (info['name'] or '').lower()
                    pid = info['pid']

                    # 1. 检查可疑进程名
                    if self._is_suspicious_name(proc_name):
                        result['suspicious_count'] += 1
                        result['suspicious_names'].append(proc_name)
                        result['suspicious_details'].append({
                            'pid': pid,
                            'name': info['name'],
                            'exe': info['exe'] or 'unknown',
                            'cmdline': ' '.join(info['cmdline'] or [])[:200],
                            'reason': '已知可疑进程名',
                        })

                    # 2. 检查异常 CPU
                    cpu = info['cpu_percent'] or 0
                    if cpu > self.cpu_threshold:
                        result['high_cpu_count'] += 1
                        result['high_cpu_details'].append({
                            'pid': pid,
                            'name': info['name'],
                            'cpu': f"{cpu:.1f}%",
                        })

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                except Exception as e:
                    self.logger.debug(f"进程 {pid} 扫描跳过: {e}")
                    continue

        except Exception as e:
            self.logger.error(f"进程扫描异常: {e}")

        return result

    def _is_suspicious_name(self, name: str) -> bool:
        """检查进程名是否可疑"""
        name_lower = name.lower()
        for suspect in self._suspicious_names:
            if suspect in name_lower or name_lower in suspect:
                return True
        return False

