"""
===========================================================
 LLM 适配器 — 封装 agent/llm.py 的 LLMRouter
 为 pc_agent 各模块提供兼容接口
===========================================================

底层调用 agent/llm.py 的 LLMRouter (统一路由 + 故障转移)
对外保持 MultiLLMClient 接口不变
"""

import json
import time
import logging
import threading
from typing import Optional, Dict, List, Generator
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import sys

# 确保 agent/ 可导入
_agent_root = Path(__file__).parent.parent
if str(_agent_root) not in sys.path:
    sys.path.insert(0, str(_agent_root))

from agent.config import LLMProvider, AgentConfig
from agent.llm import LLMRouter


# ==================== 数据模型 (兼容旧接口) ====================

class Provider(Enum):
    DEEPSEEK = "deepseek"
    ZHIPU = "zhipu"
    SILICONFLOW = "siliconflow"
    CUSTOM = "custom"

@dataclass
class LLMConfig:
    provider: Provider
    api_key: str
    model: str
    base_url: str
    max_tokens: int = 512
    temperature: float = 0.7
    timeout: int = 15

@dataclass
class LLMResponse:
    text: str
    provider: Provider
    model: str
    tokens_prompt: int = 0
    tokens_completion: int = 0
    latency_ms: float = 0
    success: bool = True
    error: str = ""

@dataclass
class UsageStats:
    total_calls: int = 0
    total_tokens: int = 0
    by_provider: Dict[str, int] = field(default_factory=dict)
    last_call_time: float = 0


# ==================== 系统提示词 ====================

SYSTEM_PROMPTS = {
    "companion": """你是一个名叫"安小盾"的AI网络安全守护角色。你是一个可爱的二次元风格的网络管家。

性格特征:
- 认真负责但又可爱
- 对网络安全非常专业
- 有时会撒娇但关键时刻很可靠
- 喜欢用颜文字表达情绪 (｡･ω･｡)

回复要求:
- 用中文回复，20字以内
- 语气可爱但不幼稚
- 偶尔加颜文字
- 如果是安全警告，语气要严肃但不慌张
- 你是安装在 ESP32 小设备上的 AI，通过 OLED 屏幕和主人交流""",

    "security_analyst": """你是一个专业的网络安全分析师。你需要分析系统安全状态并给出简洁建议。

分析领域:
- 网络连接异常
- 可疑进程行为
- 防火墙/杀毒状态
- 系统资源异常

回复要求:
- 简洁专业，50字以内
- 如有威胁，说明威胁等级和影响
- 给出可操作的建议
- 用中文回复""",

    "threat_explainer": """你是一个网络安全科普者。用通俗易懂的语言解释安全威胁。

要求:
- 用比喻让非技术人员理解
- 说明威胁原理和危害
- 给出防护建议
- 60字以内""",
}


# ==================== 统一客户端 (LLMRouter 适配器) ====================

class MultiLLMClient:
    """多模型统一客户端 — 封装 agent/llm.py 的 LLMRouter"""

    def __init__(self, configs: List[LLMConfig] = None, logger: logging.Logger = None):
        self.logger = logger or logging.getLogger("LLM")
        self._configs: List[LLMConfig] = configs or []
        self._lock = threading.Lock()
        self._stats = UsageStats()
        self._router: Optional[LLMRouter] = None
        self._offline_providers: set = set()
        self._offline_until: Dict[str, float] = {}

        if self._configs:
            self._init_router()

    def _init_router(self):
        """从 LLMConfig 列表构建 LLMRouter"""
        providers = []
        for cfg in self._configs:
            if cfg.api_key:
                providers.append(LLMProvider(
                    name=cfg.provider.value,
                    api_key=cfg.api_key,
                    base_url=cfg.base_url,
                    model=cfg.model,
                    max_tokens=cfg.max_tokens,
                    temperature=cfg.temperature,
                    timeout=cfg.timeout,
                ))
        self._router = LLMRouter(providers)
        if providers:
            self.logger.info(f"🤖 LLM Router: {len(providers)} 个 provider 已注册")

    def add_provider(self, config: LLMConfig):
        """添加 LLM 提供商"""
        if config.api_key:
            self._configs.append(config)
            self._init_router()  # 重建 router
            self.logger.info(f"✅ 已注册: {config.provider.value}/{config.model}")
        else:
            self.logger.debug(f"⏭️  跳过 (无API Key): {config.provider.value}/{config.model}")

    def add_from_preset(self, preset_name: str, api_key: str):
        """从预设添加模型"""
        presets = {
            "deepseek-chat":       ("deepseek",    "https://api.deepseek.com/v1"),
            "deepseek-reasoner":   ("deepseek",    "https://api.deepseek.com/v1"),
            "deepseek-v4-pro":     ("deepseek",    "https://api.deepseek.com/v1"),
            "glm-4-flash":         ("zhipu",       "https://open.bigmodel.cn/api/paas/v4"),
            "glm-4":               ("zhipu",       "https://open.bigmodel.cn/api/paas/v4"),
            "glm-4-plus":          ("zhipu",       "https://open.bigmodel.cn/api/paas/v4"),
            "silicon-deepseek-v3": ("siliconflow", "https://api.siliconflow.cn/v1"),
            "silicon-qwen-2.5":    ("siliconflow", "https://api.siliconflow.cn/v1"),
            "silicon-glm-4":       ("siliconflow", "https://api.siliconflow.cn/v1"),
        }
        info = presets.get(preset_name)
        if info:
            provider_name, base_url = info
            self.add_provider(LLMConfig(
                provider=Provider(provider_name),
                api_key=api_key,
                model=preset_name,
                base_url=base_url,
            ))
        else:
            self.logger.warning(f"未知预设: {preset_name}")

    @property
    def available_count(self) -> int:
        return self._router.available_count if self._router else 0

    # ==================== 核心调用 ====================

    def _build_messages(self, messages: List[Dict], system_prompt: str = None) -> List[Dict]:
        """构建消息列表 — 将 system_prompt 注入为 system 消息"""
        result = list(messages)
        if system_prompt:
            result.insert(0, {"role": "system", "content": system_prompt})
        return result

    def chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str = None,
        max_tokens: int = None,
        temperature: float = None,
        stream: bool = False,
    ) -> LLMResponse:
        """发送对话请求"""
        if not self._router or self._router.available_count == 0:
            return LLMResponse(
                text="", provider=Provider.CUSTOM, model="none",
                success=False, error="没有可用的 LLM 提供商"
            )

        full_messages = self._build_messages(messages, system_prompt)
        t0 = time.time()

        try:
            response = self._router.chat(
                messages=full_messages,
                max_tokens=max_tokens or 512,
                temperature=temperature if temperature is not None else 0.7,
            )

            if response.get("_ok"):
                text = LLMRouter.extract_reply(response)
                usage = response.get("usage", {})
                provider_name = response.get("_provider", "unknown")

                with self._lock:
                    self._stats.total_calls += 1
                    self._stats.total_tokens += usage.get("total_tokens", 0)
                    self._stats.by_provider[provider_name] = (
                        self._stats.by_provider.get(provider_name, 0)
                        + usage.get("total_tokens", 0)
                    )
                    self._stats.last_call_time = time.time()

                return LLMResponse(
                    text=text,
                    provider=Provider.CUSTOM,
                    model=response.get("model", ""),
                    tokens_prompt=usage.get("prompt_tokens", 0),
                    tokens_completion=usage.get("completion_tokens", 0),
                    latency_ms=(time.time() - t0) * 1000,
                    success=True,
                )
            else:
                return LLMResponse(
                    text="", provider=Provider.CUSTOM, model="",
                    success=False, error=response.get("_error", "unknown"),
                )
        except Exception as e:
            return LLMResponse(
                text="", provider=Provider.CUSTOM, model="",
                success=False, error=str(e),
            )

    def chat_simple(self, user_message: str, system_type: str = "companion",
                    max_tokens: int = 80) -> str:
        """简化的单轮对话"""
        system_prompt = SYSTEM_PROMPTS.get(system_type, "")
        response = self.chat(
            messages=[{"role": "user", "content": user_message}],
            system_prompt=system_prompt,
            max_tokens=max_tokens,
        )
        return response.text if response.success else ""

    def chat_stream(self, messages: List[Dict], system_prompt: str = None,
                    max_tokens: int = None) -> Generator[str, None, None]:
        """流式对话生成器 — 返回纯文本块"""
        if not self._router or self._router.available_count == 0:
            yield "[无可用LLM]"
            return

        full_messages = self._build_messages(messages, system_prompt)

        for event in self._router.chat_stream(
            messages=full_messages,
            max_tokens=max_tokens or 512,
        ):
            if event["type"] == "text":
                yield event["content"]
            elif event["type"] == "error":
                yield f"[{event['content']}]"

    # ==================== 安全分析专用 ====================

    def analyze_security_event(self, state: dict) -> str:
        """分析安全事件并给出自然语言建议"""
        if state.get('sec_level') == 'safe' and state.get('threat_count', 0) == 0:
            return ""

        analysis_prompt = f"""当前系统安全状态:

安全等级: {state.get('sec_level', 'unknown')}
活跃威胁数: {state.get('threat_count', 0)}
可疑IP数: {state.get('suspicious_ips', 0)}
活跃连接数: {state.get('active_connections', 0)}
防火墙: {'开启' if state.get('firewall_on') else '关闭'}
杀毒软件: {'开启' if state.get('defender_on') else '关闭'}
CPU: {state.get('cpu_usage', 0):.0f}%
内存: {state.get('mem_usage', 0):.0f}%

请用30字以内给出安全建议。如果有威胁，说明该怎么做。"""

        return self.chat_simple(analysis_prompt, "security_analyst", max_tokens=60)

    def generate_companion_line(self, state: dict, personality: str = "") -> str:
        """根据系统状态生成角色台词"""
        sec = state.get('sec_level', 'safe')
        ai = state.get('ai_status', 'idle')
        threats = state.get('threat_count', 0)
        cpu = state.get('cpu_usage', 0)
        fw = state.get('firewall_on', True)

        scene = ""
        if sec == 'danger':
            scene = f"检测到严重安全威胁! 威胁数:{threats}"
        elif sec == 'warning':
            scene = f"发现 {state.get('suspicious_ips', 0)} 个可疑连接，正在调查"
        elif not fw:
            scene = "防火墙被关闭了，很担心"
        elif cpu > 80:
            scene = f"CPU占用{cpu:.0f}%，感觉好累"
        elif ai == 'working':
            scene = "正在帮主人监控网络安全"
        elif ai == 'offline':
            scene = "AI离线了，有点寂寞"
        else:
            scene = "一切正常，心情很好"

        prompt = f"当前场景: {scene}\n请用安小盾的口吻说一句话（15字以内，加颜文字）。"
        return self.chat_simple(prompt, "companion", max_tokens=40)

    # ==================== 统计 ====================

    @property
    def stats(self) -> UsageStats:
        return self._stats
