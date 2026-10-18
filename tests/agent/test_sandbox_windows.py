"""agent/sandbox.py 的 Windows 真实路径验证（Job Object）。

**为什么用子进程跑**：`tests/agent/test_sandbox.py` 在模块层把
`sys.modules["ctypes"]` 换成了 MagicMock，而且这个替换会污染整个 pytest 进程 ——
`agent.sandbox` 里 `import ctypes` 绑到的就是那个 mock。真实的结构体布局与
Win32 调用必须在**干净的解释器**里验证，否则测的是 mock。

子进程也正好贴近真实运行方式：产品就是这么用的。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

_PROBE = r"""
import ctypes, json, subprocess, sys
sys.path.insert(0, {root!r})
from agent.sandbox import (
    IO_COUNTERS, JOBOBJECT_BASIC_LIMIT_INFORMATION as BASIC,
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION as EXT,
    assign_process_to_job, close_job_handle, create_job_object,
)

out = {{
    "sizeof_basic": ctypes.sizeof(BASIC),
    "sizeof_iocounters": ctypes.sizeof(IO_COUNTERS),
    "sizeof_ext": ctypes.sizeof(EXT),
    "io_offset": EXT.IoInfo.offset,
}}

# 真建一个作业并把进程放进去，再问内核「它在作业里吗」
job = create_job_object("GuardianPytestProbe", memory_mb=256)
proc = subprocess.Popen("cmd /c ping -n 2 127.0.0.1 >nul", shell=True)
assigned = assign_process_to_job(job, proc._handle)
in_job = ctypes.c_int(0)
ctypes.windll.kernel32.IsProcessInJob(
    ctypes.c_void_p(proc._handle), None, ctypes.byref(in_job))
proc.wait(timeout=20)
close_job_handle(job)

out["assigned"] = bool(assigned)
out["in_job"] = bool(in_job.value)
print("PROBE_RESULT=" + json.dumps(out))
"""


@pytest.fixture(scope="module")
def probe():
    """在干净解释器里跑一次探测，三个用例共用结果。"""
    if sys.platform != "win32":
        pytest.skip("Job Object 是 Windows 专有 API")
    result = subprocess.run(
        [sys.executable, "-u", "-c", _PROBE.format(root=str(PROJECT_ROOT))],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=120, cwd=str(PROJECT_ROOT),
    )
    line = next((ln for ln in (result.stdout or "").splitlines()
                 if ln.startswith("PROBE_RESULT=")), None)
    if line is None:
        pytest.fail(f"探测脚本没有输出结果\nstdout={result.stdout}\nstderr={result.stderr}")
    import json

    return json.loads(line[len("PROBE_RESULT="):])


@pytest.mark.skipif(sys.platform != "win32", reason="Job Object 是 Windows 专有 API")
class TestJobObjectOnWindows:

    def test_struct_layout_matches_win32(self, probe):
        """布局必须与 Win32 逐字节一致。

        回归守卫：这里曾经把 IoInfo 写成 `c_uint64 * 2`（16 字节）而真正的
        IO_COUNTERS 是 48 字节，sizeof 变成 112 而非 144 —— 于是
        SetInformationJobObject 在任何机器上都返回 ERROR_BAD_LENGTH(24)，
        整个 Job Object 层从来就没生效过，而自审计还把原因误诊成「需要提权」。
        """
        assert probe["sizeof_iocounters"] == 48
        assert probe["sizeof_basic"] == 64
        assert probe["sizeof_ext"] == 144
        assert probe["io_offset"] == 64

    def test_job_object_creation_succeeds(self, probe):
        """能建成作业 —— 结构体修好之前这一步必定抛 OSError(24)。"""
        assert "sizeof_ext" in probe

    def test_process_is_actually_placed_in_the_job(self, probe):
        """不止「建成了」，还要问内核确认进程真的在作业里。"""
        assert probe["assigned"] is True
        assert probe["in_job"] is True


_TIMEOUT_PROBE = r"""
import sys, time
sys.path.insert(0, {root!r})
from agent.sandbox import SandboxExecutor

started = time.time()
result = SandboxExecutor().execute("ping -n 30 127.0.0.1", timeout=2)
elapsed = time.time() - started
print("TIMEOUT_PROBE=" + str(round(elapsed, 1)) + "|" + str(bool(result.get("killed"))))
"""


@pytest.mark.skipif(sys.platform != "win32", reason="`ping -n` 是 Windows 语法")
class TestTimeoutIsActuallyBounded:
    """超时必须真的生效。

    回归用例。修复前：`Popen.kill()` 只杀直接子进程（`shell=True` 时是 cmd.exe），
    孙进程继续攥着 stdout 管道，后续 `communicate()` 等不到 EOF ——
    `pc_agent/sandbox_audit.log` 里记过一条 `tasklist /v`：15s 超时，实际 **625 秒**。

    修复方式：超时后先 `taskkill /F /T` 杀掉整棵树，再关 Job Object 兜底，
    最后才去回收输出（回收失败就直接放弃，绝不再挂住）。
    """

    def test_long_command_is_killed_promptly(self):
        result = subprocess.run(
            [sys.executable, "-u", "-c", _TIMEOUT_PROBE.format(root=str(PROJECT_ROOT))],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120, cwd=str(PROJECT_ROOT),
        )
        line = next((ln for ln in (result.stdout or "").splitlines()
                     if ln.startswith("TIMEOUT_PROBE=")), None)
        if line is None:
            pytest.fail(f"探测脚本没有输出结果\nstdout={result.stdout}\nstderr={result.stderr}")

        elapsed_str, killed_str = line[len("TIMEOUT_PROBE="):].split("|")
        elapsed = float(elapsed_str)
        assert killed_str == "True", "超时后应当标记 killed"
        # 2s 超时 + 5s 回收上限 + 进程启动开销，给到 15s 已经很宽松
        assert elapsed < 15, f"超时未被约束：{elapsed}s（曾经实测 625s）"
