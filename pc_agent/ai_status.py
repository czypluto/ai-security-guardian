"""
AI 状态追踪模块 —— 实时反映 AI 助手的工作状态
可对接 Claude API、本地 LLM、或通过系统状态推断
"""

import logging
import time
import os
import json
from typing import Dict
from pathlib import Path


class AIStatusTracker:
    """追踪 AI 助手状态并推送到设备"""

    def __init__(self, config: dict, logger: logging.Logger):
        self.config = config
        self.logger = logger
        self._api_url = config.get('api_url', 'http://localhost:11434')
        self._last_status = 'idle'
        self._status_file = Path(os.environ.get('TEMP', '/tmp')) / 'ai_guardian_status.json'

    def get_status(self) -> Dict:
        """获取 AI 当前状态

        检测逻辑:
        1. 检查 Claude Code / AI 进程是否在运行
        2. 检查是否有活跃的网络请求
        3. 检查状态文件 (由 AI 工具主动写入)
        """
        status = {
            'status': 'idle',
            'task': '',
            'progress': 0,
        }

        # 方法1: 读取状态文件 (最可靠)
        file_status = self._read_status_file()
        if file_status:
            return file_status

        # 方法2: 进程检测
        ai_processes = self._detect_ai_processes()
        if ai_processes:
            status['status'] = 'working'
            status['task'] = ai_processes.get('name', 'AI Assistant')
        else:
            status['status'] = 'idle'
            status['task'] = ''

        return status

    def _read_status_file(self) -> Dict:
        """读取 AI 工具写入的状态文件"""
        try:
            if self._status_file.exists():
                # 检查文件是否太旧 (>60秒没更新)
                mtime = self._status_file.stat().st_mtime
                if time.time() - mtime < 60:
                    with open(self._status_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    return {
                        'status': data.get('status', 'idle'),
                        'task': data.get('task', ''),
                        'progress': data.get('progress', 0),
                    }
        except Exception:
            pass
        return {}

    def _detect_ai_processes(self) -> Dict:
        """检测正在运行的 AI 相关进程"""
        try:
            import psutil

            ai_keywords = [
                'claude', 'claude-cli', 'claude.exe',
                'python', 'node',
                'copilot', 'codex',
                'cursor', 'windsurf',
            ]

            for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'cpu_percent']):
                try:
                    info = proc.info
                    cmdline = ' '.join((info.get('cmdline') or [])).lower()

                    # 检测 Claude CLI
                    if 'claude' in cmdline and ('--model' in cmdline or 'claude.ai' in cmdline):
                        return {'name': 'Claude AI', 'pid': info['pid']}

                    # 检测 AI IDE
                    if any(kw in cmdline for kw in ['claude', 'anthropic', 'openai']):
                        if info.get('cpu_percent', 0) > 5:  # 活跃使用
                            return {'name': 'AI Tool Active', 'pid': info['pid']}

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass

        return {}

    def set_status(self, status: str, task: str = '', progress: int = 0):
        """主动设置 AI 状态 (供外部调用)"""
        data = {
            'status': status,
            'task': task,
            'progress': progress,
            'timestamp': time.time(),
        }
        try:
            with open(self._status_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as e:
            self.logger.debug(f"状态文件写入失败: {e}")

    def set_idle(self):
        self.set_status('idle', '', 0)

    def set_working(self, task: str = '', progress: int = 0):
        self.set_status('working', task, progress)

    def set_alert(self, reason: str = ''):
        self.set_status('alert', reason, 0)
