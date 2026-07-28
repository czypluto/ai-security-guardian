"""
pytest 共享 fixtures 和 Mock 工具
"""

import sys
import os
import pytest
from unittest.mock import MagicMock, patch

# 将 pc_agent 加入 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'pc_agent'))


@pytest.fixture
def mock_logger():
    """提供一个静默的 Mock Logger"""
    logger = MagicMock()
    logger.debug = MagicMock()
    logger.info = MagicMock()
    logger.warning = MagicMock()
    logger.error = MagicMock()
    return logger


@pytest.fixture
def sample_state():
    """提供标准测试用的系统状态"""
    return {
        'ai_status': 'idle',
        'ai_task': '',
        'ai_progress': 0,
        'sec_level': 'safe',
        'threat_count': 0,
        'blocked_count': 5,
        'last_threat': '',
        'active_connections': 25,
        'suspicious_ips': 0,
        'net_status': 'normal',
        'firewall_on': True,
        'defender_on': True,
        'cpu_usage': 30.0,
        'mem_usage': 45.0,
        'uptime': 36000,
        'messages': [],
    }


@pytest.fixture
def danger_state(sample_state):
    """危险状态的系统数据"""
    sample_state.update({
        'sec_level': 'danger',
        'threat_count': 3,
        'suspicious_ips': 5,
        'net_status': 'under_attack',
        'messages': ['检测到可疑连接: 10.0.0.5:4444'],
    })
    return sample_state


@pytest.fixture
def warning_state(sample_state):
    """警告状态的系统数据"""
    sample_state.update({
        'sec_level': 'warning',
        'threat_count': 1,
        'suspicious_ips': 2,
        'net_status': 'suspicious',
        'messages': ['网络异常: 2 个可疑连接'],
    })
    return sample_state
