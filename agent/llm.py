"""LLM Router — multi-provider with function calling, failover, and streaming."""
from __future__ import annotations

import json
import time
import logging
import threading
from typing import Optional, Generator

import requests

from .config import LLMProvider


logger = logging.getLogger("Guardian.LLM")


class LLMRouter:
    """Multi-provider LLM client with function calling support."""

    def __init__(self, providers: list[LLMProvider], enable_failover: bool = True):
        self._providers = [p for p in providers if p.enabled]
        self._active_idx = 0
        self._lock = threading.Lock()
        self._failover = enable_failover
        self._offline_until: dict[str, float] = {}
        self._session = requests.Session()

    @property
    def available_count(self) -> int:
        return len(self._providers)

    @property
    def active_provider(self) -> Optional[LLMProvider]:
        if not self._providers:
            return None
        return self._providers[self._active_idx]

    # ================================================================
    #  Main API
    # ================================================================

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        max_tokens: int = 1024,
        temperature: float = 0.7,
        stream: bool = False,
    ) -> dict:
        """Send chat request with optional function calling. Returns parsed response."""
        errors = []
        for attempt in range(len(self._providers)):
            idx = (self._active_idx + attempt) % len(self._providers)
            provider = self._providers[idx]

            if self._is_offline(provider):
                continue

            response = self._call_api(provider, messages, tools, tool_choice,
                                      max_tokens, temperature, stream)
            if response.get("_ok"):
                with self._lock:
                    self._active_idx = idx
                return response

            errors.append(f"{provider.name}: {response.get('_error', 'unknown')}")
            self._mark_offline(provider, 30)

        return {"_ok": False, "_error": "; ".join(errors),
                "choices": [{"message": {"content": f"[All LLMs unavailable: {errors}]"}}]}

    def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> Generator[dict, None, None]:
        """Streaming chat with tool call support."""
        if not self._providers:
            yield {"type": "error", "content": "[No LLM providers available]"}
            return

        provider = self._providers[self._active_idx]
        yield from self._call_stream(provider, messages, tools, max_tokens, temperature)

    # ================================================================
    #  Internal — API calls
    # ================================================================

    def _call_api(self, provider: LLMProvider, messages: list[dict],
                  tools: list[dict] | None, tool_choice: str,
                  max_tokens: int, temperature: float, stream: bool) -> dict:
        """Single provider API call."""
        t0 = time.time()
        body = {
            "model": provider.model,
            "messages": messages,
            "max_tokens": max_tokens or provider.max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = tool_choice

        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        }

        # Zhipu needs extra header
        if "bigmodel" in provider.base_url:
            headers["Accept"] = "application/json"

        try:
            resp = self._session.post(
                provider.chat_url, json=body, headers=headers,
                timeout=provider.timeout,
            )
            latency_ms = (time.time() - t0) * 1000

            if resp.status_code == 200:
                data = resp.json()
                data["_ok"] = True
                data["_provider"] = provider.name
                data["_latency_ms"] = latency_ms
                return data

            error_msg = self._extract_error(resp)
            return {"_ok": False, "_error": f"{resp.status_code}: {error_msg}"}

        except requests.Timeout:
            return {"_ok": False, "_error": "timeout"}
        except requests.ConnectionError:
            return {"_ok": False, "_error": "connection failed"}
        except Exception as e:
            return {"_ok": False, "_error": str(e)}

    def _call_stream(self, provider: LLMProvider, messages: list[dict],
                     tools: list[dict] | None, max_tokens: int,
                     temperature: float) -> Generator[dict, None, None]:
        """Streaming API call."""
        body = {
            "model": provider.model,
            "messages": messages,
            "max_tokens": max_tokens or provider.max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        }
        if "bigmodel" in provider.base_url:
            headers["Accept"] = "application/json"

        try:
            resp = self._session.post(
                provider.chat_url, json=body, headers=headers,
                timeout=provider.timeout, stream=True,
            )
            if resp.status_code != 200:
                yield {"type": "error", "content": f"[{provider.name} error: {resp.status_code}]"}
                return

            tool_calls_acc: dict[int, dict] = {}
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})

                    # Text content
                    content = delta.get("content", "")
                    if content:
                        yield {"type": "text", "content": content}

                    # Tool calls
                    for tc in delta.get("tool_calls", []):
                        idx = tc.get("index", 0)
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": tc.get("id", ""),
                                "function": {"name": "", "arguments": ""},
                            }
                        acc = tool_calls_acc[idx]
                        if "id" in tc:
                            acc["id"] = tc["id"]
                        if tc.get("function", {}).get("name"):
                            acc["function"]["name"] += tc["function"]["name"]
                        if tc.get("function", {}).get("arguments"):
                            acc["function"]["arguments"] += tc["function"]["arguments"]

                    finish = chunk.get("choices", [{}])[0].get("finish_reason")
                    if finish == "tool_calls" and tool_calls_acc:
                        for idx in sorted(tool_calls_acc.keys()):
                            tc = tool_calls_acc[idx]
                            # Parse JSON args
                            try:
                                tc["function"]["arguments_parsed"] = json.loads(
                                    tc["function"]["arguments"])
                            except json.JSONDecodeError:
                                tc["function"]["arguments_parsed"] = {}
                            yield {"type": "tool_call", "tool_call": tc}

                except json.JSONDecodeError:
                    continue

        except Exception as e:
            yield {"type": "error", "content": f"[Stream error: {e}]"}

    # ================================================================
    #  Helpers
    # ================================================================

    def _extract_error(self, resp) -> str:
        try:
            err = resp.json().get("error", {})
            return err.get("message", str(resp.status_code))
        except Exception:
            return resp.text[:200]

    def _is_offline(self, provider: LLMProvider) -> bool:
        until = self._offline_until.get(provider.name, 0)
        if time.time() < until:
            return True
        self._offline_until.pop(provider.name, None)
        return False

    def _mark_offline(self, provider: LLMProvider, seconds: float):
        self._offline_until[provider.name] = time.time() + seconds

    @staticmethod
    def extract_reply(response: dict) -> str:
        """Extract text reply from API response."""
        try:
            return response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return ""

    @staticmethod
    def extract_tool_calls(response: dict) -> list[dict]:
        """Extract tool calls from API response."""
        try:
            msg = response["choices"][0]["message"]
            return msg.get("tool_calls", [])
        except (KeyError, IndexError, TypeError):
            return []

    @staticmethod
    def has_tool_calls(response: dict) -> bool:
        """Check if response contains tool calls."""
        try:
            finish = response["choices"][0].get("finish_reason", "")
            return finish == "tool_calls"
        except (KeyError, IndexError, TypeError):
            return False
