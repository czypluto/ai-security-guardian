"""本地嵌入服务的按需启停管理器（transformers 架构）。

模型平时在磁盘、不占显存；知识库第一次要嵌入时自动拉起服务，
空闲 N 分钟后自动停止（模型回磁盘、显存释放）。
Windows 侧通过 WSL 调用 scripts/run_embed.sh / stop_embed.sh。

与前身 VLLMManager 的区别：
    - 服务端由 vLLM 换成 transformers 直载（scripts/embed_server.py）；
    - 健康探测由 `/v1/models` 改为 `/health`（新服务暴露的是 /health，探错端点会
      每次都判定"没起"，从而反复重复拉起）；
    - 就绪等待由 180s 降到 90s（模型加载实测约 20s，留足余量即可）。

设 GUARDIAN_EMBED_NO_AUTOSTART=1 可关闭自动拉起——当你希望手动起服务、
或与另一个项目共用同一台机器上的嵌入服务时用。
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time
from pathlib import Path

logger = logging.getLogger("Guardian.EmbedService")


class EmbedServiceManager:
    def __init__(self, url: str = "http://localhost:8099",
                 idle_timeout: int = 300,
                 scripts_dir: str = None,
                 autostart: bool = True):
        self.url = url.rstrip("/")
        self.idle_timeout = idle_timeout
        self.autostart = autostart
        self._lock = threading.Lock()
        self._last_use = 0.0
        self._running = False
        self._scripts_dir = scripts_dir or self._default_scripts_dir()
        self._idle_thread = None

    def _default_scripts_dir(self) -> str:
        """把项目 scripts 目录转成 WSL 路径（C:\\... -> /mnt/c/...）。"""
        s = str(Path(__file__).parent.parent).replace("\\", "/")
        m = re.match(r"^([A-Za-z]):(.*)$", s)
        if m:
            return f"/mnt/{m.group(1).lower()}{m.group(2)}/scripts"
        return f"{s}/scripts"

    # ---- 状态 ----

    def is_running(self) -> bool:
        try:
            import requests
            r = requests.get(f"{self.url}/health", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    # ---- 启动 / 停止 ----

    def ensure_running(self) -> bool:
        """确保嵌入服务在跑；不在则拉起并等待就绪。返回是否可用。"""
        with self._lock:
            self._last_use = time.time()
            if self.is_running():
                self._running = True
                return True
            if not self.autostart:
                logger.warning("嵌入服务未运行，且已关闭自动拉起（GUARDIAN_EMBED_NO_AUTOSTART）")
                return False
            logger.info("按需启动嵌入服务 ...")
            self._launch()
            deadline = time.time() + 90
            while time.time() < deadline:
                if self.is_running():
                    self._running = True
                    logger.info("嵌入服务就绪")
                    self._start_idle_thread()
                    return True
                time.sleep(3)
            logger.warning("嵌入服务启动超时（90s），本次嵌入跳过")
            return False

    def _launch(self):
        try:
            cmd = f"bash {self._scripts_dir}/run_embed.sh"
            subprocess.run(["wsl", "-e", "bash", "-lc", cmd],
                           timeout=30, capture_output=True)
        except Exception as e:
            logger.warning("拉起嵌入服务失败: %s", e)

    def stop(self):
        with self._lock:
            if not self.is_running():
                self._running = False
                return
            try:
                cmd = f"bash {self._scripts_dir}/stop_embed.sh"
                subprocess.run(["wsl", "-e", "bash", "-lc", cmd],
                               timeout=30, capture_output=True)
            except Exception as e:
                logger.warning("停止嵌入服务失败: %s", e)
            self._running = False
            logger.info("嵌入服务已停止（空闲超时），模型回磁盘、显存释放")

    def touch(self):
        with self._lock:
            self._last_use = time.time()

    # ---- 空闲自动停止 ----

    def _start_idle_thread(self):
        if self._idle_thread and self._idle_thread.is_alive():
            return
        self._idle_thread = threading.Thread(target=self._idle_loop, daemon=True)
        self._idle_thread.start()

    def _idle_loop(self):
        while True:
            time.sleep(30)
            with self._lock:
                idle = time.time() - self._last_use
                running = self._running
            if running and idle > self.idle_timeout:
                logger.info("嵌入服务空闲 %ds，自动停止", int(idle))
                self.stop()


_manager = None
_manager_lock = threading.Lock()


def get_embed_manager(url: str = "http://localhost:8099",
                      idle_timeout: int = 300) -> EmbedServiceManager:
    """全局单例。"""
    global _manager
    with _manager_lock:
        if _manager is None:
            autostart = os.getenv("GUARDIAN_EMBED_NO_AUTOSTART", "") not in ("1", "true", "True")
            _manager = EmbedServiceManager(url=url, idle_timeout=idle_timeout,
                                           autostart=autostart)
    return _manager
