"""
进程监控模块 —— 检测可疑进程和异常行为
"""

import logging
from typing import Dict, List

import psutil


class ProcessMonitor:
    """进程行为监控"""

    # Windows 系统进程 (白名单)
    SYSTEM_PROCESSES = {
        'system', 'system idle process', 'registry', 'smss.exe',
        'csrss.exe', 'wininit.exe', 'winlogon.exe', 'services.exe',
        'lsass.exe', 'svchost.exe', 'dwm.exe', 'explorer.exe',
        'taskhostw.exe', 'spoolsv.exe', 'sihost.exe', 'taskhost.exe',
        'fontdrvhost.exe', 'ctfmon.exe', 'searchindexer.exe',
        'searchui.exe', 'startmenuexperiencehost.exe', 'runtimebroker.exe',
        'shellexperiencehost.exe', 'textinputhost.exe', 'securityhealthservice.exe',
        'securityhealthsystray.exe', 'msmpeng.exe', 'nissrv.exe',
    }

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
        self._previous_scan = {}
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
            'high_mem_count': 0,
            'cpu_percent': psutil.cpu_percent(interval=0.5),
        }

        try:
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent',
                                              'connections', 'exe', 'cmdline', 'create_time']):
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

                    # 3. 检查异常内存
                    mem = info['memory_percent'] or 0
                    if mem > self.mem_threshold:
                        result['high_mem_count'] += 1

                    # 4. 检查新增进程 (对比上次扫描)
                    if pid not in self._previous_scan:
                        if not self._is_system_process(proc_name):
                            # 新出现的非系统进程
                            pass  # 可在详细模式记录

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                except Exception as e:
                    self.logger.debug(f"进程 {pid} 扫描跳过: {e}")
                    continue

        except Exception as e:
            self.logger.error(f"进程扫描异常: {e}")

        # 更新历史
        self._previous_scan = {p.pid: p.info['name']
                               for p in psutil.process_iter(['pid', 'name'])}

        return result

    def _is_suspicious_name(self, name: str) -> bool:
        """检查进程名是否可疑"""
        name_lower = name.lower()
        for suspect in self._suspicious_names:
            if suspect in name_lower or name_lower in suspect:
                return True
        return False

    def _is_system_process(self, name: str) -> bool:
        """检查是否为系统进程"""
        return name.lower() in self.SYSTEM_PROCESSES

    def get_process_tree(self, pid: int) -> List[Dict]:
        """获取进程树"""
        tree = []
        try:
            proc = psutil.Process(pid)
            tree.append({
                'pid': proc.pid,
                'name': proc.name(),
                'children': [{'pid': c.pid, 'name': c.name()} for c in proc.children(recursive=True)],
            })
        except Exception:
            pass
        return tree

    def kill_process(self, pid: int) -> bool:
        """终止指定进程 (需管理员权限)"""
        try:
            proc = psutil.Process(pid)
            proc.terminate()
            proc.wait(timeout=5)
            self.logger.info(f"✅ 已终止进程: {proc.name()} (PID:{pid})")
            return True
        except psutil.NoSuchProcess:
            self.logger.warning(f"进程 PID:{pid} 已不存在")
            return True
        except psutil.AccessDenied:
            self.logger.error(f"❌ 权限不足, 无法终止 PID:{pid}")
            return False
        except Exception as e:
            self.logger.error(f"❌ 终止进程失败: {e}")
            return False
