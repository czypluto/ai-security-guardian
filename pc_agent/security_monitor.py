"""
安全监控模块 —— 综合安全事件收集
整合 Windows 事件日志、安全审计等
"""

import logging
import threading
from datetime import datetime
from typing import Dict, List


class SecurityMonitor:
    """Windows 安全事件监控"""

    def __init__(self, config: dict, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self._event_cache = []
        self._last_check = datetime.now()

    def collect_events(self) -> List[Dict]:
        """收集安全事件"""
        events = []

        # 尝试读取 Windows 安全事件日志
        try:
            events.extend(self._read_security_log())
        except Exception as e:
            self.logger.debug(f"安全日志读取失败: {e}")

        # 尝试读取 Windows Defender 事件
        try:
            events.extend(self._read_defender_log())
        except Exception as e:
            self.logger.debug(f"Defender 日志读取失败: {e}")

        self._last_check = datetime.now()
        return events

    def _read_security_log(self) -> List[Dict]:
        """读取 Windows 安全事件日志"""
        events = []
        try:
            import win32evtlog

            server = None  # 本地
            log_type = 'Security'
            flags = win32evtlog.EVENTLOG_SEQUENTIAL_READ | win32evtlog.EVENTLOG_FORWARDS_READ

            hand = win32evtlog.OpenEventLog(server, log_type)

            suspicious_event_ids = [
                4625,  # 登录失败
                4648,  # 使用显式凭据尝试登录
                4672,  # 特殊权限登录
                4688,  # 进程创建
                4697,  # 服务安装
                4720,  # 用户账户创建
                4726,  # 用户账户删除
                4732,  # 成员添加到安全本地组
                4768,  # Kerberos TGT 请求
                4769,  # Kerberos 服务票证请求
                4776,  # 凭据验证失败
                4798,  # 用户本地组成员枚举
                5140,  # 网络共享访问
                5156,  # Windows 筛选平台连接
            ]

            try:
                while True:
                    events_batch = win32evtlog.ReadEventLog(hand, flags, 0)
                    if not events_batch:
                        break

                    for event in events_batch:
                        if event.EventID in suspicious_event_ids:
                            events.append({
                                'id': event.EventID,
                                'time': event.TimeGenerated.Format(),
                                'source': event.SourceName,
                                'computer': event.ComputerName,
                                'category': event.EventCategory,
                            })
            except Exception:
                pass

            win32evtlog.CloseEventLog(hand)

        except ImportError:
            pass  # pywin32 未安装
        except Exception as e:
            self.logger.debug(f"EventLog 读取异常: {e}")

        return events

    def _read_defender_log(self) -> List[Dict]:
        """读取 Windows Defender 事件"""
        events = []
        try:
            import win32evtlog

            log_type = 'Microsoft-Windows-Windows Defender/Operational'
            hand = win32evtlog.OpenEventLog(None, log_type)
            flags = win32evtlog.EVENTLOG_SEQUENTIAL_READ | win32evtlog.EVENTLOG_FORWARDS_READ

            try:
                while True:
                    batch = win32evtlog.ReadEventLog(hand, flags, 0)
                    if not batch:
                        break
                    for event in batch:
                        events.append({
                            'id': event.EventID,
                            'time': event.TimeGenerated.Format(),
                            'source': 'Windows Defender',
                            'type': 'defender',
                        })
            except Exception:
                pass

            win32evtlog.CloseEventLog(hand)
        except Exception:
            pass

        return events

    def get_summary(self) -> Dict:
        """获取安全摘要"""
        events = self.collect_events()

        failed_logins = [e for e in events if e['id'] == 4625]
        new_processes = [e for e in events if e['id'] == 4688]
        new_users = [e for e in events if e['id'] == 4720]

        return {
            'total_events': len(events),
            'failed_logins': len(failed_logins),
            'new_processes': len(new_processes),
            'new_users': len(new_users),
            'risk_level': 'high' if len(failed_logins) > 5 else 'medium' if failed_logins else 'low',
            'last_check': self._last_check.isoformat(),
        }
