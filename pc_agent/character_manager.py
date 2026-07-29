"""
角色管理器 —— 管理二次元角色表情包和互动行为
Character Manager - Expression sets, companion behaviors, message library
v2.0: 集成 LLM 动态对话 (DeepSeek/智谱/硅基流动)
"""

import json
import logging
import random
import time
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from llm_client import MultiLLMClient


class CharacterManager:
    """
    管理角色的:
    - 表情与安全状态映射
    - 对话/反应库
    - 陪伴行为 (随机台词, 定时互动)
    - 自定义角色导入
    """

    # 表情枚举 (与固件一致)
    EXP_IDLE = 0
    EXP_HAPPY = 1
    EXP_WORKING = 2
    EXP_WORRIED = 3
    EXP_ANGRY = 4
    EXP_SLEEP = 5
    # 6 = EXP_LOVE (已废弃)
    EXP_GREETING = 7

    # 默认角色台词库
    DEFAULT_LINES = {
        # 开机
        'startup': [
            "你好! 我是安小盾~",
            "今天也请多指教! ✨",
            "网络安全就交给我吧!",
            "主人! 好久不见~",
            "系统启动完成! 🛡️",
        ],
        # 安全 - 一切正常
        'safe_idle': [
            "一切安好! (｡･ω･｡)",
            "今天也很和平呢~",
            "我在看着哦~ 👀",
            "网络很安静...",
            "✨ 系统运行正常",
        ],
        # 安全 + AI 工作中
        'safe_working': [
            "正在守护中... 🛡️",
            "主人忙吧,我盯着!",
            "扫描进行中~",
            "后台监控运行中~",
            "交给我吧! 🤖",
        ],
        # 警告 - 有可疑情况
        'warning': [
            "嗯? 好像有点不对劲...",
            "检测到异常连接...",
            "让我调查一下这个IP",
            "有点可疑呢... ⚡",
            "正在追踪可疑来源",
        ],
        # 危险 - 检测到威胁
        'danger': [
            "危险! 主人小心! 🚨",
            "检测到攻击!!!",
            "我已经封锁了可疑IP!",
            "防火墙启动! 别怕!",
            "正在反击!!! 💢",
        ],
        # 威胁被清除
        'threat_cleared': [
            "呼,搞定了~ 😤",
            "威胁已清除! ✨",
            "安全了! 不愧是我~",
            "搞定! 小菜一碟~",
        ],
        # 长时间空闲
        'long_idle': [
            "主人还在吗...?",
            "好安静啊... zzZ",
            "有点困了呢... 😴",
            "有人理我一下吗~",
        ],
        # 用户互动
        'greeting': [
            "主人好! ★o★",
            "耶! 主人来看我了~",
            "今天有什么需要?",
            "随叫随到! 🫡",
        ],
        'praise': [
            "诶嘿~被夸了 ♡",
            "谢谢主人! ^o^",
            "我会继续努力的!",
            "主人最好啦! ♡_♡",
        ],
        # CPU/内存异常
        'cpu_high': [
            "CPU 有点烫... 🥵",
            "好累啊... 喘不过气",
            "能不能关掉几个程序?",
        ],
        # 防火墙关闭
        'firewall_off': [
            "主人! 防火墙怎么关了!",
            "没有防火墙我好害怕...",
            "快开防火墙!!! >_<",
        ],
    }

    def __init__(self, logger: logging.Logger, llm_client: 'MultiLLMClient' = None):
        self.logger = logger
        self.llm = llm_client
        self._llm_enabled = llm_client is not None and llm_client.available_count > 0
        self._last_line_time = 0
        self._line_cooldown = 15  # 主动说话冷却时间(秒)
        self._last_expression = self.EXP_IDLE
        self._last_state_hash = ''
        self._interaction_count = 0
        self._consecutive_safe_rounds = 0
        self._used_lines = set()
        self._custom_lines = {}
        self._character_name = "安小盾"
        self._character_file = None
        self._llm_fail_count = 0
        self._llm_cooldown_until = 0  # LLM 失败后的冷却

    def load_character(self, path: str):
        """加载自定义角色配置"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self._character_name = data.get('name', self._character_name)
            self._custom_lines = data.get('lines', {})
            self._character_file = path
            self.logger.info(f"✅ 已加载角色: {self._character_name}")
        except Exception as e:
            self.logger.error(f"角色配置加载失败: {e}")

    # ==================== 状态 → 表情映射 ====================

    def get_expression(self, state: dict) -> int:
        """根据安全/AI状态返回合适的表情"""
        sec_level = state.get('sec_level', 'safe')
        ai_status = state.get('ai_status', 'idle')
        threat_count = state.get('threat_count', 0)

        if sec_level == 'danger':
            return self.EXP_ANGRY
        if sec_level == 'warning':
            return self.EXP_WORRIED
        if ai_status == 'working':
            return self.EXP_WORKING
        if ai_status == 'alert':
            return self.EXP_WORRIED
        if ai_status == 'offline':
            return self.EXP_SLEEP

        # 安全 + 空闲 → 开心
        if threat_count == 0:
            return self.EXP_HAPPY
        return self.EXP_IDLE

    # ==================== 台词生成 ====================

    def get_line(self, state: dict, trigger: str = 'auto') -> Optional[str]:
        """根据状态触发生成台词

        trigger 类型:
          - 'auto': 自动触发 (冷却制)
          - 'startup': 开机触发
          - 'threat': 威胁触发 (立即)
          - 'cleared': 威胁清除
          - 'interaction': 用户互动
        """
        now = time.time()

        # 紧急触发 (无冷却)
        if trigger in ('threat', 'cleared', 'startup', 'interaction'):
            return self._pick_line(trigger, state)

        # 自动触发 (有冷却)
        if now - self._last_line_time < self._line_cooldown:
            return None

        # 安全等级变化时主动说话
        state_hash = f"{state.get('sec_level')}|{state.get('ai_status')}"
        if state_hash != self._last_state_hash:
            self._last_state_hash = state_hash
            self._last_line_time = now
            return self._pick_adaptive_line(state)

        # 长时间安全 → 偶尔说句话
        sec_level = state.get('sec_level', 'safe')
        if sec_level == 'safe':
            self._consecutive_safe_rounds += 1
        else:
            self._consecutive_safe_rounds = 0

        # 每 5 分钟随机说一次 (概率 5%)
        if self._consecutive_safe_rounds > 20 and random.random() < 0.05:
            self._last_line_time = now
            self._consecutive_safe_rounds = 0
            return self._pick_adaptive_line(state)

        return None

    def _pick_adaptive_line(self, state: dict) -> str:
        """根据状态选台词 (LLM优先，本地库兜底)"""

        # 尝试 LLM 动态生成
        if self._llm_enabled and time.time() > self._llm_cooldown_until:
            llm_line = self._try_llm_companion_line(state)
            if llm_line:
                return llm_line

        # 本地台词库兜底
        sec = state.get('sec_level', 'safe')
        ai = state.get('ai_status', 'idle')
        cpu = state.get('cpu_usage', 0)
        fw = state.get('firewall_on', True)

        if not fw:
            return self._pick_from('firewall_off')
        if cpu > 80:
            return self._pick_from('cpu_high')
        if sec == 'danger':
            return self._pick_from('danger')
        if sec == 'warning':
            return self._pick_from('warning')
        if ai == 'working':
            return self._pick_from('safe_working')
        if self._consecutive_safe_rounds > 60:
            return self._pick_from('long_idle')
        return self._pick_from('safe_idle')

    def _try_llm_companion_line(self, state: dict) -> Optional[str]:
        """尝试用 LLM 生成陪伴台词"""
        if self.llm is None or self.llm.available_count == 0:
            return None

        try:
            line = self.llm.generate_companion_line(state)
            if line and len(line.strip()) >= 2:
                self._llm_fail_count = 0
                return line.strip()
        except Exception as e:
            self.logger.debug(f"LLM 台词生成失败: {e}")

        # 连续失败降级
        self._llm_fail_count += 1
        if self._llm_fail_count >= 5:
            self.logger.warning("LLM 连续失败5次，暂停使用30秒")
            self._llm_cooldown_until = time.time() + 30
            self._llm_fail_count = 0

        return None

    def analyze_security_with_llm(self, state: dict) -> Optional[str]:
        """使用 LLM 分析安全状态并给出建议"""
        if not self._llm_enabled or self.llm is None:
            return None
        try:
            return self.llm.analyze_security_event(state)
        except Exception as e:
            self.logger.debug(f"LLM 安全分析失败: {e}")
            return None

    @property
    def is_llm_available(self) -> bool:
        return self._llm_enabled and time.time() > self._llm_cooldown_until

    def _pick_line(self, trigger: str, state: dict) -> str:
        """按触发类型选台词"""
        mapping = {
            'startup': 'startup',
            'threat': 'danger',
            'cleared': 'threat_cleared',
            'interaction': 'greeting',
        }
        category = mapping.get(trigger)
        if category:
            return self._pick_from(category)
        return self._pick_adaptive_line(state)

    def _pick_from(self, category: str) -> str:
        """从指定类别随机选一句 (避免重复)"""
        # 合并自定义和默认台词
        lines = self._custom_lines.get(category, []) + self.DEFAULT_LINES.get(category, [])
        if not lines:
            return "..."

        # 优先选没用过的
        fresh = [l for l in lines if l not in self._used_lines]
        if not fresh:
            self._used_lines.clear()
            fresh = lines

        line = random.choice(fresh)
        self._used_lines.add(line)
        if len(self._used_lines) > 50:
            self._used_lines.clear()
        return line

    # ==================== 指令生成 ====================

    def generate_device_commands(self, state: dict) -> List[dict]:
        """生成发送给设备的角色指令"""
        commands = []

        # 表情
        exp = self.get_expression(state)
        if exp != self._last_expression:
            commands.append({
                "cmd": "expression",
                "expression": exp,
            })
            self._last_expression = exp

        # 台词
        line = self.get_line(state)
        if line:
            commands.append({
                "cmd": "say",
                "text": line,
            })

        # 开机触达
        if self._interaction_count == 0:
            commands.append({
                "cmd": "say",
                "text": self._pick_from('startup'),
            })
            commands.append({
                "cmd": "expression",
                "expression": self.EXP_GREETING,
            })

        self._interaction_count += 1
        return commands

    def force_greeting(self) -> List[dict]:
        """强制触发欢迎"""
        return [
            {"cmd": "expression", "expression": self.EXP_GREETING},
            {"cmd": "say", "text": self._pick_from('greeting')},
        ]

    def force_alert(self, message: str) -> List[dict]:
        """强制触发告警"""
        return [
            {"cmd": "expression", "expression": self.EXP_ANGRY},
            {"cmd": "say", "text": f"! {message}"},
        ]

    @property
    def name(self) -> str:
        return self._character_name
