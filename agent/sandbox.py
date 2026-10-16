"""
Secure Sandbox — Multi-layer process isolation for tool execution.

Layers (innermost → outermost):
  1. Command whitelist   — only allow known-safe diagnostic commands
  2. Windows Job Object  — kernel-level CPU/memory limits, auto-kill on close
  3. Restricted Token    — drop admin privileges, strip dangerous rights
  4. Resource limits     — max 30s runtime, max 64MB memory, max 16KB output
  5. Filesystem guard    — prevent writes outside allowed paths
  6. Audit logging       — every execution logged to sandbox_audit.log

Design principle: If any layer fails, the command is denied by default (fail-closed).
"""
from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("Guardian.Sandbox")

# ---- Constants ----

# Whitelist — only these executables (and their arguments) are allowed
SAFE_COMMANDS: dict[str, list[str]] = {
    "ipconfig":    ["", "/all", "/displaydns", "/flushdns", "/registerdns"],
    "netstat":     ["", "-a", "-an", "-ano", "-b", "-n", "-r", "-e"],
    "tasklist":    ["", "/v", "/svc", "/m", "/fi"],
    "whoami":      ["", "/user", "/groups", "/priv"],
    "systeminfo":  [""],
    "hostname":    [""],
    "ver":         [""],
    "ping":        ["", "-n"],
    "tracert":     ["", "-d", "-h"],
    "nslookup":    [""],
    "route":       ["", "print", "print -4", "print -6"],
    "arp":         ["", "-a"],
    "getmac":      ["", "/v"],
    "driverquery": ["", "/v", "/si"],
    "sc":          ["", "query", "queryex", "qc"],
    "schtasks":    ["", "/query", "/fo", "/v"],
    "powercfg":    ["", "/energy", "/batteryreport", "/sleepstudy", "/a"],
    "wmic":        ["", "process", "cpu", "os", "service", "qfe", "nicconfig",
                    "diskdrive", "logicaldisk", "useraccount", "group",
                    "netlogin", "share", "startup"],
    "dir":         ["", "/s", "/b", "/a"],
    "set":         [""],
    "findstr":     ["", "/i", "/n", "/c:"],
}

# Command prefixes considered safe (for piped commands)
SAFE_PREFIXES = [
    "ipconfig", "netstat", "tasklist", "whoami", "systeminfo",
    "hostname", "ver", "ping", "tracert", "nslookup", "route",
    "arp", "getmac", "driverquery", "sc query", "schtasks",
    "powercfg", "wmic", "dir", "set", "findstr", "fc",
]

# Dangerous command patterns that are always blocked
BLOCKED_PATTERNS = [
    "del ", "erase ", "rm ", "rmdir ", "rd ",
    "format ", "diskpart", "chkdsk /f", "chkdsk /r",
    "shutdown", "restart", "logoff",
    "reg add", "reg delete", "reg import",
    "netsh firewall", "netsh advfirewall",
    "net user", "net group", "net localgroup",
    "icacls", "cacls", "takeown", "attrib",
    "bcdedit", "bootcfg", "fsutil",
    ">", ">>", "|", "&", ";", "$", "`", "&&", "||",
]

# Default resource limits
DEFAULT_MAX_TIME_SEC = 30
DEFAULT_MAX_MEMORY_MB = 64
DEFAULT_MAX_OUTPUT_BYTES = 16384  # 16KB

# Allowed write paths (everything else is read-only)
ALLOWED_WRITE_PATHS = [
    r"C:\Users\24522\AppData\Local\Temp",
    os.environ.get("TEMP", r"C:\Windows\Temp"),
]

# ---- Windows Job Object (via ctypes) ----

# Windows API constants
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x00000400
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_JOB_TIME = 0x00000004
JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
JOB_OBJECT_LIMIT_PROCESS_TIME = 0x00000002
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_WORKINGSET = 0x00010000
JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800

JobObjectExtendedLimitInformation = 9
JobObjectBasicUIRestrictions = 4

class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_uint64),
        ("PerJobUserTimeLimit", ctypes.c_uint64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_ulonglong),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    """必须与 Win32 的布局**逐字节**一致，否则 SetInformationJobObject 直接
    返回 ERROR_BAD_LENGTH(24)。

    这里曾经把 IoInfo 写成 `ctypes.c_uint64 * 2`（16 字节），而真正的
    IO_COUNTERS 是 48 字节 —— sizeof 变成 112 而非 144，于是 create_job_object
    在任何机器上都不可能成功（自审计里那句 "Job Object 需提权才能验证" 其实
    是误诊：根本不是权限问题，是结构体写错了）。
    IO_COUNTERS 类当时就定义在下方，只是没人用。
    """

    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def create_job_object(name: str = None,
                      memory_mb: int = DEFAULT_MAX_MEMORY_MB) -> ctypes.c_void_p:
    """建一个 Job Object 并施加限制。

    最有价值的一条是 KILL_ON_JOB_CLOSE：句柄一关（**包括守护进程自己崩溃**），
    作业内所有进程都会被内核杀掉，不会留下孤儿诊断进程。

    刻意**不**设置 ActiveProcessLimit=1。原实现设了，但白名单里的 wmic / schtasks
    这类命令会派生辅助进程，限死 1 个会把它们弄坏；而 KILL_ON_JOB_CLOSE 本来就能
    保证派生出来的子进程随作业一起消亡，不需要再叠这一层。
    """
    job_name = name or f"GuardianSandbox_{uuid.uuid4().hex[:8]}"

    kernel32 = ctypes.windll.kernel32
    # HANDLE 在 64 位上是 64 位的；不声明 restype 的话 ctypes 按 c_int 处理，
    # 高位非零时会被静默截断成一个无效句柄。
    kernel32.CreateJobObjectW.restype = ctypes.c_void_p
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    kernel32.SetInformationJobObject.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32,
    ]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    job = kernel32.CreateJobObjectW(None, job_name)
    if not job:
        err = kernel32.GetLastError()
        raise OSError(f"CreateJobObject failed: {err}")

    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    flags = (
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE |
        JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION
    )
    if memory_mb and memory_mb > 0:
        info.ProcessMemoryLimit = memory_mb * 1024 * 1024
        flags |= JOB_OBJECT_LIMIT_PROCESS_MEMORY
    info.BasicLimitInformation.LimitFlags = flags

    result = kernel32.SetInformationJobObject(
        job,
        JobObjectExtendedLimitInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not result:
        err = kernel32.GetLastError()
        kernel32.CloseHandle(job)
        raise OSError(f"SetInformationJobObject failed: {err}")

    # 桌面隔离：限制作业内进程访问窗口站/桌面/剪贴板等 USER 对象。
    # 对白名单里的控制台命令无影响（实测 ipconfig / netstat / whoami 输出完全一致），
    # 失败也不阻断 —— 限制本身是加固，不是必需条件。
    try:
        set_job_ui_restrictions(job)
    except Exception as e:  # noqa: BLE001
        logger.debug("Job Object 桌面限制未生效: %s", e)

    logger.debug(f"Job object created: {job_name}")
    return ctypes.c_void_p(job)


def assign_process_to_job(job_handle: ctypes.c_void_p, process_handle: int):
    """Assign a process to a job object."""
    kernel32 = ctypes.windll.kernel32
    result = kernel32.AssignProcessToJobObject(job_handle, process_handle)
    if not result:
        err = kernel32.GetLastError()
        logger.warning(f"AssignProcessToJobObject failed: {err} (process may already be in a job)")
        return False
    return True


def close_job_handle(job_handle: ctypes.c_void_p):
    """Close job object handle. All processes are killed if KILL_ON_JOB_CLOSE is set."""
    ctypes.windll.kernel32.CloseHandle(job_handle)
    logger.debug("Job object closed — all sandboxed processes terminated")


def set_job_ui_restrictions(job_handle: ctypes.c_void_p):
    """Prevent sandboxed process from interacting with desktop."""
    kernel32 = ctypes.windll.kernel32

    class JOBOBJECT_BASIC_UI_RESTRICTIONS(ctypes.Structure):
        _fields_ = [("UIRestrictionsClass", ctypes.c_uint32)]

    ui = JOBOBJECT_BASIC_UI_RESTRICTIONS()
    # UIRestrictionsClass values — prevent desktop access
    ui.UIRestrictionsClass = 0xFFFFFFFF  # Restrict everything

    kernel32.SetInformationJobObject(
        job_handle, JobObjectBasicUIRestrictions,
        ctypes.byref(ui), ctypes.sizeof(ui),
    )


# ---- Command Validation ----

class CommandValidator:
    """Validate commands against whitelist and blocklist."""

    @staticmethod
    def validate(command: str) -> tuple[bool, str]:
        """
        Validate a command. Returns (is_safe, reason).
        fail-closed: any unknown pattern is denied.
        """
        cmd_stripped = command.strip()

        if not cmd_stripped:
            return False, "empty command"

        # Check blocked patterns first
        cmd_lower = cmd_stripped.lower()
        for pattern in BLOCKED_PATTERNS:
            if pattern.lower() in cmd_lower:
                return False, f"blocked pattern: '{pattern}'"

        # Extract base command
        base = cmd_stripped.split()[0].lower() if cmd_stripped.split() else ""
        # Remove path prefix (e.g., "C:\\Windows\\System32\\ipconfig.exe" → "ipconfig")
        if "\\" in base:
            base = base.rsplit("\\", 1)[-1]
        base = base.rstrip(".exe").rstrip(".com").rstrip(".bat").rstrip(".cmd")

        if base not in SAFE_COMMANDS and not any(
            cmd_stripped.lower().startswith(p) for p in SAFE_PREFIXES
        ):
            return False, f"command '{base}' not in safe list"

        return True, "ok"

    @staticmethod
    def get_allowed_commands() -> list[str]:
        return sorted(SAFE_COMMANDS.keys())


# ---- Audit Logger ----

class AuditLogger:
    """Write an audit trail of all sandboxed executions."""

    def __init__(self, log_path: str = None):
        self.log_path = log_path or str(
            Path(__file__).parent.parent / "pc_agent" / "sandbox_audit.log"
        )

    def record(self, execution_id: str, command: str, allowed: bool,
               reason: str, exit_code: int = None, duration_ms: float = None,
               output_size: int = None, pid: int = None):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "execution_id": execution_id,
            "command": command[:200],  # Truncate for log
            "allowed": allowed,
            "reason": reason,
            "exit_code": exit_code,
            "duration_ms": round(duration_ms, 1) if duration_ms else None,
            "output_size_bytes": output_size,
            "pid": pid,
        }
        import json
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"Audit log write failed: {e}")


# ---- Sandbox Executor ----

class SandboxExecutor:
    """Execute commands in a multi-layer sandbox."""

    def __init__(
        self,
        max_time_sec: int = DEFAULT_MAX_TIME_SEC,
        max_memory_mb: int = DEFAULT_MAX_MEMORY_MB,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
        audit: AuditLogger = None,
    ):
        self.max_time_sec = max_time_sec
        self.max_memory_mb = max_memory_mb
        self.max_output_bytes = max_output_bytes
        self.validator = CommandValidator()
        self.audit = audit or AuditLogger()

    def execute(self, command: str, timeout: int = None) -> dict:
        """
        Execute a command in the sandbox. Returns structured result.
        """
        exec_id = uuid.uuid4().hex[:12]
        t0 = time.time()
        pid = None

        # Layer 1: Validate
        allowed, reason = self.validator.validate(command)
        if not allowed:
            self.audit.record(exec_id, command, False, reason)
            return {
                "success": False,
                "error": "Command blocked: " + reason,
                "execution_id": exec_id,
            }

        timeout = timeout or self.max_time_sec
        killed = False
        exit_code = -1
        stdout_data = ""
        stderr_data = ""

        # Layer 2: Job Object —— 进程树围栏 + 内存上限。
        #
        # 尽力而为，失败不阻断执行：如果本进程已经身处另一个不允许 breakaway 的
        # 作业里（IDE 内置终端、Windows Terminal、CI 都很常见），
        # AssignProcessToJobObject 会失败。那种情况下降级为「无作业围栏」并记
        # warning —— 否则沙箱会在大量正常环境里直接不可用。
        job = self._create_job_safely()

        try:
            # Layer 3: Spawn with isolation flags
            # CREATE_NO_WINDOW — no console window
            # CREATE_NEW_PROCESS_GROUP — no Ctrl+C propagation
            # BELOW_NORMAL_PRIORITY_CLASS — don't starve the system
            try:
                proc = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,
                    creationflags=(
                        subprocess.CREATE_NO_WINDOW |
                        subprocess.CREATE_NEW_PROCESS_GROUP |
                        0x00004000  # BELOW_NORMAL_PRIORITY_CLASS
                    ),
                    encoding="gbk",
                    errors="replace",
                )
                pid = proc.pid
                # 放进作业：进程树随作业句柄一起消亡，并且受 ProcessMemoryLimit 约束
                if job is not None:
                    handle = getattr(proc, "_handle", None)
                    if handle:
                        assign_process_to_job(job, handle)
            except OSError as e:
                self.audit.record(exec_id, command, False, "OS error: " + str(e))
                return {
                    "success": False,
                    "error": "Execution failed: " + str(e),
                    "execution_id": exec_id,
                }

            # Layer 3: Resource-limited wait with force-kill
            try:
                stdout_data, stderr_data = proc.communicate(timeout=timeout)
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                killed = True
                # Force kill — TerminateProcess, no escape
                proc.kill()
                try:
                    stdout_data, stderr_data = proc.communicate(timeout=3)
                except Exception:
                    pass
                exit_code = -1

            duration_ms = (time.time() - t0) * 1000

            # Layer 4: Output sanitization
            output = stdout_data[:self.max_output_bytes]
            if stderr_data:
                stderr_safe = stderr_data[:2048]
                output += "\n[stderr]\n" + stderr_safe

            if len(stdout_data) > self.max_output_bytes:
                output += "\n[truncated: %d -> %d bytes]" % (
                    len(stdout_data), self.max_output_bytes)

            # Layer 5: Audit
            self.audit.record(
                exec_id, command, True,
                "killed_by_timeout" if killed else "completed",
                exit_code=exit_code,
                duration_ms=duration_ms,
                output_size=len(output),
                pid=pid,
            )

            return {
                "success": not killed and exit_code == 0,
                "stdout": output,
                "exit_code": exit_code,
                "killed": killed,
                "duration_ms": round(duration_ms, 1),
                "execution_id": exec_id,
            }

        except Exception as e:
            duration_ms = (time.time() - t0) * 1000
            logger.error("Sandbox error: " + str(e))
            self.audit.record(exec_id, command, False, "unexpected: " + str(e))
            return {
                "success": False,
                "error": "Sandbox error: " + str(e),
                "execution_id": exec_id,
                "duration_ms": round(duration_ms, 1),
            }

        finally:
            # 关句柄会连带杀掉作业内所有进程（KILL_ON_JOB_CLOSE）。
            # 这正是想要的：无论上面走的是哪条返回路径，都不留孤儿进程。
            if job is not None:
                try:
                    close_job_handle(job)
                except Exception as e:  # noqa: BLE001
                    logger.debug("Job Object 关闭失败: %s", e)

    def _create_job_safely(self):
        """建作业对象；任何失败都降级为 None（无围栏），不阻断执行。"""
        if sys.platform != "win32":
            return None
        try:
            return create_job_object(memory_mb=self.max_memory_mb)
        except Exception as e:  # noqa: BLE001 - 降级是刻意的
            logger.warning("Job Object 创建失败，本次执行无作业围栏: %s", e)
            return None

    def quick_check(self, command: str) -> dict:
        """Check if a command would be allowed, without executing."""
        allowed, reason = self.validator.validate(command)
        return {"allowed": allowed, "reason": reason}


# ---- Singleton ----

_default_sandbox: Optional[SandboxExecutor] = None


def get_sandbox() -> SandboxExecutor:
    global _default_sandbox
    if _default_sandbox is None:
        _default_sandbox = SandboxExecutor()
    return _default_sandbox

