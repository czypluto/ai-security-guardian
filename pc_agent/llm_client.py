"""
============================================================
 统一多模型 LLM 客户端
 Multi-Provider LLM Client

 支持:
   - DeepSeek    (api.deepseek.com)
   - 智谱 AI     (open.bigmodel.cn)
   - 硅基流动     (api.siliconflow.cn)
   - 任何 OpenAI 兼容 API

 特性:
   - 统一 OpenAI-compatible 接口
   - 自动故障转移 (failover)
   - 角色扮演系统提示词
   - 安全事件分析
   - Token 用量统计
   - 流式输出
============================================================
"""

import json
import time
import logging
import threading
from typing import Optional, Dict, List, Generator, Any
from dataclasses import dataclass, field
from enum import Enum

import requests


# ==================== 数据模型 ====================

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


# ==================== 预设模型配置 ====================

PRESET_MODELS = {
    "deepseek-chat": LLMConfig(
        provider=Provider.DEEPSEEK,
        api_key="",  # 需要填入
        model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
        max_tokens=512,
        temperature=0.7,
    ),
    "deepseek-reasoner": LLMConfig(
        provider=Provider.DEEPSEEK,
        api_key="",
        model="deepseek-reasoner",
        base_url="https://api.deepseek.com/v1",
        max_tokens=1024,
        temperature=0.3,
    ),
    "glm-4-flash": LLMConfig(
        provider=Provider.ZHIPU,
        api_key="",
        model="glm-4-flash",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        max_tokens=512,
        temperature=0.7,
    ),
    "glm-4": LLMConfig(
        provider=Provider.ZHIPU,
        api_key="",
        model="glm-4",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        max_tokens=1024,
        temperature=0.7,
    ),
    "glm-4-plus": LLMConfig(
        provider=Provider.ZHIPU,
        api_key="",
        model="glm-4-plus",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        max_tokens=1024,
        temperature=0.7,
    ),
    "silicon-deepseek-v3": LLMConfig(
        provider=Provider.SILICONFLOW,
        api_key="",
        model="deepseek-ai/DeepSeek-V3",
        base_url="https://api.siliconflow.cn/v1",
        max_tokens=512,
        temperature=0.7,
    ),
    "silicon-qwen-2.5": LLMConfig(
        provider=Provider.SILICONFLOW,
        api_key="",
        model="Qwen/Qwen2.5-7B-Instruct",
        base_url="https://api.siliconflow.cn/v1",
        max_tokens=512,
        temperature=0.7,
    ),
    "silicon-glm-4": LLMConfig(
        provider=Provider.SILICONFLOW,
        api_key="",
        model="THUDM/glm-4-9b-chat",
        base_url="https://api.siliconflow.cn/v1",
        max_tokens=512,
        temperature=0.7,
    ),
}

# 免费/廉价模型推荐
FREE_MODELS = [
    "silicon-deepseek-v3",   # 硅基流动有免费额度
    "silicon-qwen-2.5",      # 同上
    "glm-4-flash",           # 智谱免费模型
]


# ==================== 系统提示词 ====================

SYSTEM_PROMPTS = {
    # 角色陪伴 - 安小盾
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

    # 安全分析
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

    # 威胁解说
    "threat_explainer": """你是一个网络安全科普者。用通俗易懂的语言解释安全威胁。

要求:
- 用比喻让非技术人员理解
- 说明威胁原理和危害
- 给出防护建议
- 60字以内""",
}


# ==================== 统一客户端 ====================

class MultiLLMClient:
    """多模型统一客户端"""

    def __init__(self, configs: List[LLMConfig] = None, logger: logging.Logger = None):
        self.logger = logger or logging.getLogger("LLM")
        self._configs: List[LLMConfig] = []
        self._active_idx = 0
        self._lock = threading.Lock()
        self._stats = UsageStats()
        self._session = requests.Session()
        self._offline_providers: set = set()  # 暂时不可用的 provider
        self._offline_until: Dict[str, float] = {}  # provider → 恢复时间

        if configs:
            for c in configs:
                self.add_provider(c)

    def add_provider(self, config: LLMConfig):
        """添加 LLM 提供商"""
        if config.api_key:  # 只添加有 key 的
            self._configs.append(config)
            self.logger.info(f"✅ 已注册: {config.provider.value}/{config.model}")
        else:
            self.logger.debug(f"⏭️  跳过 (无API Key): {config.provider.value}/{config.model}")

    def add_from_preset(self, preset_name: str, api_key: str):
        """从预设添加模型"""
        if preset_name in PRESET_MODELS:
            config = PRESET_MODELS[preset_name]
            config.api_key = api_key
            self.add_provider(config)
        else:
            self.logger.warning(f"未知预设: {preset_name}")

    @property
    def available_count(self) -> int:
        return len(self._configs)

    # ==================== 核心调用 ====================

    def chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str = None,
        max_tokens: int = None,
        temperature: float = None,
        stream: bool = False,
    ) -> LLMResponse:
        """发送对话请求，自动选择可用 provider"""
        if not self._configs:
            return LLMResponse(
                text="", provider=Provider.CUSTOM, model="none",
                success=False, error="没有可用的 LLM 提供商"
            )

        # 构建完整消息
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        # 轮询尝试所有 provider
        errors = []
        for attempt in range(len(self._configs)):
            idx = (self._active_idx + attempt) % len(self._configs)
            config = self._configs[idx]

            # 检查是否在冷却期
            if config.provider.value in self._offline_providers:
                if time.time() < self._offline_until.get(config.provider.value, 0):
                    continue
                self._offline_providers.discard(config.provider.value)

            response = self._call_api(config, full_messages, max_tokens, temperature, stream)
            if response.success:
                with self._lock:
                    self._active_idx = idx
                return response

            errors.append(f"{config.provider.value}: {response.error}")

        # 全部失败
        return LLMResponse(
            text="",
            provider=Provider.CUSTOM,
            model="all-failed",
            success=False,
            error="; ".join(errors),
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
        """流式对话生成器"""
        if not self._configs:
            yield "[无可用LLM]"
            return

        config = self._configs[self._active_idx]
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        try:
            payload = {
                "model": config.model,
                "messages": full_messages,
                "max_tokens": max_tokens or config.max_tokens,
                "temperature": config.temperature,
                "stream": True,
            }
            headers = {
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            }
            url = f"{config.base_url}/chat/completions"

            with self._session.post(url, json=payload, headers=headers,
                                     timeout=config.timeout, stream=True) as resp:
                if resp.status_code != 200:
                    yield f"[{config.provider.value} 错误: {resp.status_code}]"
                    return

                for line in resp.iter_lines(decode_unicode=True):
                    if line and line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            delta = data.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            yield f"[流式错误: {e}]"

    # ==================== 内部调用 ====================

    def _call_api(
        self,
        config: LLMConfig,
        messages: List[Dict],
        max_tokens: int = None,
        temperature: float = None,
        stream: bool = False,
    ) -> LLMResponse:
        """调用单个 provider 的 API"""
        t0 = time.time()

        try:
            payload = {
                "model": config.model,
                "messages": messages,
                "max_tokens": max_tokens or config.max_tokens,
                "temperature": temperature if temperature is not None else config.temperature,
                "stream": False,
            }

            headers = {
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            }

            # 智谱需要额外的 header
            if config.provider == Provider.ZHIPU:
                headers["Accept"] = "application/json"

            url = f"{config.base_url}/chat/completions"
            resp = self._session.post(
                url,
                json=payload,
                headers=headers,
                timeout=config.timeout,
            )
            latency = (time.time() - t0) * 1000

            if resp.status_code == 200:
                data = resp.json()
                choice = data.get("choices", [{}])[0]
                content = choice.get("message", {}).get("content", "")
                usage = data.get("usage", {})

                # 更新统计
                with self._lock:
                    self._stats.total_calls += 1
                    self._stats.total_tokens += usage.get("total_tokens", 0)
                    self._stats.by_provider[config.provider.value] = (
                        self._stats.by_provider.get(config.provider.value, 0)
                        + usage.get("total_tokens", 0)
                    )
                    self._stats.last_call_time = time.time()

                return LLMResponse(
                    text=content,
                    provider=config.provider,
                    model=config.model,
                    tokens_prompt=usage.get("prompt_tokens", 0),
                    tokens_completion=usage.get("completion_tokens", 0),
                    latency_ms=latency,
                    success=True,
                )

            elif resp.status_code == 429:
                # Rate limit → 冷却 30 秒
                self._mark_offline(config, 30)
                return LLMResponse(
                    text="", provider=config.provider, model=config.model,
                    success=False, error=f"429 Rate Limited",
                )

            elif resp.status_code in (401, 403):
                # 认证失败 → 永久标记
                self._mark_offline(config, 3600)
                error_msg = resp.json().get("error", {}).get("message", str(resp.status_code))
                return LLMResponse(
                    text="", provider=config.provider, model=config.model,
                    success=False, error=f"认证失败: {error_msg}",
                )

            else:
                error_msg = resp.json().get("error", {}).get("message", str(resp.status_code))
                self._mark_offline(config, 60)
                return LLMResponse(
                    text="", provider=config.provider, model=config.model,
                    success=False, error=f"{resp.status_code}: {error_msg}",
                )

        except requests.Timeout:
            self._mark_offline(config, 60)
            return LLMResponse(
                text="", provider=config.provider, model=config.model,
                success=False, error="请求超时",
            )
        except requests.ConnectionError:
            self._mark_offline(config, 120)
            return LLMResponse(
                text="", provider=config.provider, model=config.model,
                success=False, error="连接失败",
            )
        except Exception as e:
            return LLMResponse(
                text="", provider=config.provider, model=config.model,
                success=False, error=str(e),
            )

    def _mark_offline(self, config: LLMConfig, seconds: float):
        """标记 provider 暂时不可用"""
        self._offline_providers.add(config.provider.value)
        self._offline_until[config.provider.value] = time.time() + seconds
        self.logger.warning(f"⚠️  {config.provider.value} 暂不可用 ({seconds}s)")

    # ==================== 安全分析专用 ====================

    def analyze_security_event(self, state: dict) -> str:
        """分析安全事件并给出自然语言建议"""
        if state.get('sec_level') == 'safe' and state.get('threat_count', 0) == 0:
            return ""  # 安全时不需要分析

        # 构建分析提示
        analysis_prompt = f"""当前系统安全状态:

安全等级: {state.get('sec_level', 'unknown')}
活跃威胁数: {state.get('threat_count', 0)}
可疑IP数: {state.get('suspicious_ips', 0)}
活跃连接数: {state.get('active_connections', 0)}
防火墙: {'开启' if state.get('firewall_on') else '关闭'}
杀毒软件: {'开启' if state.get('defender_on') else '关闭'}
CPU: {state.get('cpu_usage', 0):.0f}%
内存: {state.get('mem_usage', 0):.0f}%

最近威胁: {state.get('last_threat', '无')}
网络状态: {state.get('net_status', 'normal')}

请用30字以内给出安全建议。如果有威胁，说明该怎么做。"""

        return self.chat_simple(analysis_prompt, "security_analyst", max_tokens=60)

    def explain_threat(self, threat_description: str) -> str:
        """用通俗语言解释威胁"""
        return self.chat_simple(
            f"请用简单的话解释这是什么威胁、有什么危害: {threat_description}",
            "threat_explainer",
            max_tokens=80,
        )

    def generate_companion_line(self, state: dict, personality: str = "") -> str:
        """根据系统状态生成角色台词"""
        sec = state.get('sec_level', 'safe')
        ai = state.get('ai_status', 'idle')
        threats = state.get('threat_count', 0)
        cpu = state.get('cpu_usage', 0)
        fw = state.get('firewall_on', True)

        # 构建场景描述
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

    def get_cost_estimate(self) -> Dict[str, float]:
        """估算费用 (元)"""
        # 参考价格 (每百万token)
        prices_per_1m = {
            "deepseek-chat": 2.0,        # DeepSeek 极便宜
            "deepseek-reasoner": 4.0,
            "glm-4-flash": 0.0,          # 免费
            "glm-4": 50.0,
            "glm-4-plus": 100.0,
            "deepseek-ai/DeepSeek-V3": 2.0,
            "Qwen/Qwen2.5-7B-Instruct": 4.0,
            "THUDM/glm-4-9b-chat": 4.0,
        }

        costs = {}
        for provider, tokens in self._stats.by_provider.items():
            # 简化估算
            rate = 2.0  # 默认
            costs[provider] = tokens / 1_000_000 * rate

        return costs

    def reset_stats(self):
        self._stats = UsageStats()

    def test_connection(self) -> Dict[str, bool]:
        """快速测试所有 provider 连通性"""
        results = {}
        for config in self._configs:
            response = self._call_api(
                config,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            results[f"{config.provider.value}/{config.model}"] = response.success
        return results
