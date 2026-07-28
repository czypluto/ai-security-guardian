"""
测试 CharacterManager: 状态→表情映射, 台词生成, 去重逻辑, LLM 降级
"""

import time
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from character_manager import CharacterManager


class TestExpressionMapping:
    """状态 → 表情映射测试"""

    def setup_method(self):
        self.cm = CharacterManager(MagicMock(), llm_client=None)

    def test_danger_returns_angry(self):
        assert self.cm.get_expression({'sec_level': 'danger'}) == self.cm.EXP_ANGRY

    def test_warning_returns_worried(self):
        assert self.cm.get_expression({'sec_level': 'warning'}) == self.cm.EXP_WORRIED

    def test_working_returns_working(self):
        assert self.cm.get_expression({
            'sec_level': 'safe',
            'ai_status': 'working',
            'threat_count': 0,
        }) == self.cm.EXP_WORKING

    def test_alert_returns_worried(self):
        assert self.cm.get_expression({
            'sec_level': 'safe',
            'ai_status': 'alert',
            'threat_count': 0,
        }) == self.cm.EXP_WORRIED

    def test_offline_returns_sleep(self):
        assert self.cm.get_expression({
            'sec_level': 'safe',
            'ai_status': 'offline',
            'threat_count': 0,
        }) == self.cm.EXP_SLEEP

    def test_safe_no_threats_returns_happy(self):
        assert self.cm.get_expression({
            'sec_level': 'safe',
            'ai_status': 'idle',
            'threat_count': 0,
        }) == self.cm.EXP_HAPPY

    def test_safe_with_threats_returns_idle(self):
        assert self.cm.get_expression({
            'sec_level': 'safe',
            'ai_status': 'idle',
            'threat_count': 2,
        }) == self.cm.EXP_IDLE


class TestLineGeneration:
    """台词生成测试 (本地台词库, 不依赖 LLM)"""

    def setup_method(self):
        self.cm = CharacterManager(MagicMock(), llm_client=None)
        self.cm._line_cooldown = 0  # 消除冷却期

    def test_startup_line(self, sample_state):
        line = self.cm.get_line(sample_state, trigger='startup')
        assert line is not None
        assert len(line) >= 2

    def test_threat_line(self, danger_state):
        line = self.cm.get_line(danger_state, trigger='threat')
        assert line is not None
        assert len(line) >= 2

    def test_cleared_line(self, sample_state):
        line = self.cm.get_line(sample_state, trigger='cleared')
        assert line is not None
        assert line in self.cm.DEFAULT_LINES['threat_cleared']

    def test_interaction_line(self, sample_state):
        line = self.cm.get_line(sample_state, trigger='interaction')
        assert line is not None
        assert line in self.cm.DEFAULT_LINES['greeting']

    def test_auto_line_respects_cooldown(self, sample_state):
        self.cm._line_cooldown = 60  # 60秒冷却
        self.cm._last_line_time = time.time()  # 刚说过话
        line = self.cm.get_line(sample_state, trigger='auto')
        assert line is None  # 冷却中不出台词

    def test_danger_state_gives_danger_line(self, danger_state):
        self.cm._line_cooldown = 0
        self.cm._last_line_time = 0
        self.cm._last_state_hash = ''
        line = self.cm._pick_adaptive_line(danger_state)
        assert line in self.cm.DEFAULT_LINES['danger']

    def test_warning_state_gives_warning_line(self, warning_state):
        self.cm._line_cooldown = 0
        self.cm._last_line_time = 0
        self.cm._last_state_hash = ''
        line = self.cm._pick_adaptive_line(warning_state)
        assert line in self.cm.DEFAULT_LINES['warning']

    def test_firewall_off_line(self, sample_state):
        sample_state['firewall_on'] = False
        line = self.cm._pick_adaptive_line(sample_state)
        assert line in self.cm.DEFAULT_LINES['firewall_off']

    def test_cpu_high_line(self, sample_state):
        sample_state['cpu_usage'] = 95
        line = self.cm._pick_adaptive_line(sample_state)
        assert line in self.cm.DEFAULT_LINES['cpu_high']


class TestDeduplication:
    """台词去重逻辑"""

    def setup_method(self):
        self.cm = CharacterManager(MagicMock(), llm_client=None)

    def test_no_immediate_repeat(self):
        """同一类别不会连续重复 (概率性, 但6条台词池中1次就重复概率极低)"""
        lines = [self.cm._pick_from('startup') for _ in range(10)]
        # 至少出现过 2 种以上的台词
        assert len(set(lines)) >= 2

    def test_used_lines_reset_when_exhausted(self):
        """用过的台词集满后自动清空"""
        self.cm._used_lines = set(self.cm.DEFAULT_LINES['startup'])
        self.cm._used_lines.add('extra line')  # 超过 50 个触发清空
        for _ in range(60):
            self.cm._used_lines.add(f'line_{_}')
        # 应能正常获取台词
        line = self.cm._pick_from('startup')
        assert line is not None


class TestLLMFallback:
    """LLM 降级逻辑"""

    def test_llm_unavailable_uses_local_library(self, sample_state, mock_logger):
        """当 LLM 不可用时, 退回本地台词库"""
        cm = CharacterManager(mock_logger, llm_client=None)
        cm._line_cooldown = 0
        cm._last_line_time = 0
        cm._last_state_hash = ''

        # 不应崩溃
        line = cm._pick_adaptive_line(sample_state)
        assert line is not None
        assert len(line) >= 2

    def test_llm_available_but_fails_returns_none(self, mock_logger):
        """LLM 可用但调用失败时, 退回本地库"""
        mock_llm = MagicMock()
        type(mock_llm).available_count = PropertyMock(return_value=1)
        mock_llm.generate_companion_line.return_value = ""  # 空响应 = 失败

        cm = CharacterManager(mock_logger, llm_client=mock_llm)
        cm._llm_enabled = True
        cm._line_cooldown = 0
        cm._last_line_time = 0
        cm._last_state_hash = ''

        line = cm._pick_adaptive_line({'sec_level': 'safe', 'ai_status': 'idle',
                                        'cpu_usage': 30, 'firewall_on': True,
                                        'threat_count': 0})
        # 退回到本地台词库
        assert line is not None

    def test_llm_consecutive_failures_cooldown(self, mock_logger):
        """连续 5 次 LLM 失败后进入冷却期"""
        mock_llm = MagicMock()
        type(mock_llm).available_count = PropertyMock(return_value=1)
        mock_llm.generate_companion_line.return_value = ""

        cm = CharacterManager(mock_logger, llm_client=mock_llm)
        cm._llm_enabled = True

        # 触发 5 次失败
        for _ in range(5):
            cm._try_llm_companion_line({'sec_level': 'safe'})

        # 现在应该在冷却期
        assert cm._llm_cooldown_until > time.time()
        assert cm._llm_fail_count == 0  # 重置


class TestDeviceCommands:
    """设备指令生成"""

    def setup_method(self):
        self.cm = CharacterManager(MagicMock(), llm_client=None)

    def test_first_interaction_includes_greeting(self, sample_state):
        """首次互动生成欢迎指令"""
        self.cm._interaction_count = 0
        cmds = self.cm.generate_device_commands(sample_state)
        # 应包含 say 和 expression 指令
        cmds_by_type = {c['cmd'] for c in cmds}
        assert 'say' in cmds_by_type
        assert 'expression' in cmds_by_type

    def test_expression_change_triggers_command(self, sample_state):
        """表情变化时生成 expression 指令"""
        self.cm._last_expression = self.cm.EXP_IDLE
        self.cm._interaction_count = 99  # 非首次
        self.cm._line_cooldown = 60  # 防止台词线

        cmds = self.cm.generate_device_commands(sample_state)
        exps = [c for c in cmds if c['cmd'] == 'expression']
        # 表情从 IDLE 变为 HAPPY
        assert len(exps) >= 1
        assert exps[0]['expression'] == self.cm.EXP_HAPPY

    def test_force_greeting_commands(self):
        cmds = self.cm.force_greeting()
        assert len(cmds) == 2
        assert cmds[0]['cmd'] == 'expression'
        assert cmds[0]['expression'] == self.cm.EXP_GREETING
        assert cmds[1]['cmd'] == 'say'

    def test_force_alert_commands(self):
        cmds = self.cm.force_alert('测试威胁')
        assert len(cmds) == 2
        assert cmds[0]['cmd'] == 'expression'
        assert cmds[0]['expression'] == self.cm.EXP_ANGRY
        assert cmds[1]['cmd'] == 'say'
        assert '测试威胁' in cmds[1]['text']
