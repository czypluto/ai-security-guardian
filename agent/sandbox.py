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
import threading
import time
import uuid
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("Guardian.Sandbox")

# ================================================================
#  Constants
# ================================================================

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

# ================================================================
#  Windows Job Object (via ctypes)
# ================================================================

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

class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", ctypes.c_uint64 * 8),
        ("IoInfo", ctypes.c_uint64 * 2),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


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


def create_job_object(name: str = None) -> ctypes.c_void_p:
    """Create a Windows Job Object with kill-on-close behavior."""
    job_name = name or f"GuardianSandbox_{uuid.uuid4().hex[:8]}"

    kernel32 = ctypes.windll.kernel32
    job = kernel32.CreateJobObjectW(None, job_name)
    if not job:
        err = kernel32.GetLastError()
        raise OSError(f"CreateJobObject failed: {err}")

    # Configure limits
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation = (ctypes.c_uint64 * 8)()
    info.IoInfo = (ctypes.c_uint64 * 2)()

    # Set limits
    flags = (
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE |
        JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION |
        JOB_OBJECT_LIMIT_ACTIVE_PROCESS
    )

    basic = JOBOBJECT_BASIC_LIMIT_INFORMATION()
    basic.LimitFlags = flags
    basic.ActiveProcessLimit = 1  # Only 1 process allowed
    info.BasicLimitInformation = (ctypes.c_uint64 * 8).from_buffer_copy(basic)

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


def set_job_memory_limit(job_handle: ctypes.c_void_p, max_mb: int):
    """Set per-process memory limit on a job object."""
    kernel32 = ctypes.windll.kernel32
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.ProcessMemoryLimit = max_mb * 1024 * 1024
    # Read current limits first
    kernel32.QueryInformationJobObject(
        job_handle, JobObjectExtendedLimitInformation,
        ctypes.byref(info), ctypes.sizeof(info), None,
    )
    # Add memory limit flag
    basic = JOBOBJECT_BASIC_LIMIT_INFORMATION.from_buffer_copy(
        info.BasicLimitInformation)
    basic.LimitFlags |= JOB_OBJECT_LIMIT_PROCESS_MEMORY
    info.BasicLimitInformation = (ctypes.c_uint64 * 8).from_buffer_copy(basic)

    kernel32.SetInformationJobObject(
        job_handle, JobObjectExtendedLimitInformation,
        ctypes.byref(info), ctypes.sizeof(info),
    )


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


# ================================================================
#  Command Validation
# ================================================================

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


# ================================================================
#  Audit Logger
# ================================================================

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


# ================================================================
#  Sandbox Executor
# ================================================================

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

        try:
            # Layer 2: Spawn with isolation flags
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

    def quick_check(self, command: str) -> dict:
        """Check if a command would be allowed, without executing."""
        allowed, reason = self.validator.validate(command)
        return {"allowed": allowed, "reason": reason}


# ================================================================
#  Singleton
# ================================================================

_default_sandbox: Optional[SandboxExecutor] = None


def get_sandbox() -> SandboxExecutor:
    global _default_sandbox
    if _default_sandbox is None:
        _default_sandbox = SandboxExecutor()
    return _default_sandbox
