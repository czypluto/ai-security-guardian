"""Tool Executor — built-in security tools and MCP client."""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from .sandbox import get_sandbox
from .otx_tools import threat_check_ip, threat_check_domain, threat_check_hash, threat_pulse_search
from .defender_tools import (
    defender_quick_scan, defender_full_scan, defender_threat_list,
    defender_status, defender_update_signatures,
    nvd_cve_lookup, nvd_cve_search,
)
from .web_tools import web_search, web_fetch
from .installer import install_skill, recommend_mcp_server, list_installed_skills

logger = logging.getLogger("Guardian.Tools")

# ================================================================
#  Tool Definition
# ================================================================

def _is_admin() -> bool:
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


class ToolDef:
    """Tool definition with JSON Schema for function calling."""
    def __init__(self, name: str, description: str, parameters: dict,
                 handler: Callable, require_admin: bool = False):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler
        self.require_admin = require_admin

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": self.parameters,
                    "required": [k for k, v in self.parameters.items()
                                 if v.get("required", False)],
                },
            },
        }

    def execute(self, arguments: dict) -> str:
        if self.require_admin and not _is_admin():
            return json.dumps({"error": "Admin privileges required"}, ensure_ascii=False)
        try:
            result = self.handler(**arguments)
            if isinstance(result, dict):
                return json.dumps(result, ensure_ascii=False, default=str)
            return str(result)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)


# ================================================================
#  Tool Registry
# ================================================================

class ToolRegistry:
    """Register and execute tools."""

    def __init__(self):
        self._tools: dict[str, ToolDef] = {}
        self._mcp_tools: dict[str, dict] = {}  # MCP-discovered tools

    def register(self, tool: ToolDef):
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name) or self._mcp_tools.get(name)

    def list_all(self) -> list[ToolDef]:
        """All tools (built-in + MCP)."""
        return list(self._tools.values())

    def get_schemas(self) -> list[dict]:
        """Get OpenAI function calling schemas for all tools."""
        return [t.to_openai_schema() for t in self._tools.values()]

    def execute(self, name: str, arguments: dict) -> str:
        tool = self.get(name)
        if tool is None:
            return json.dumps({"error": f"Unknown tool: {name}"})
        if isinstance(tool, ToolDef):
            return tool.execute(arguments)
        # MCP tool
        return self._execute_mcp(name, arguments)

    def _execute_mcp(self, name: str, arguments: dict) -> str:
        return json.dumps({"error": f"MCP tool '{name}' not connected"}, ensure_ascii=False)


# ================================================================
#  Built-in Tool Implementations
# ================================================================

def _import_guardian_modules():
    """Lazy import guardian modules from pc_agent."""
    sys.path.insert(0, str(Path(__file__).parent.parent / "pc_agent"))
    from network_monitor import NetworkMonitor
    from process_monitor import ProcessMonitor
    from firewall_checker import FirewallChecker
    from security_monitor import SecurityMonitor
    return NetworkMonitor, ProcessMonitor, FirewallChecker, SecurityMonitor


_modules_lock = threading.Lock()
_modules_cache: dict[str, Any] = {}


def _get_module(name: str) -> Any:
    """Lazy singleton for guardian modules."""
    with _modules_lock:
        if name not in _modules_cache:
            NetworkMonitor, ProcessMonitor, FirewallChecker, SecurityMonitor = \
                _import_guardian_modules()
            if name == "network":
                _modules_cache[name] = NetworkMonitor({}, logger)
            elif name == "process":
                _modules_cache[name] = ProcessMonitor({}, logger)
            elif name == "firewall":
                _modules_cache[name] = FirewallChecker({}, logger)
            elif name == "security":
                _modules_cache[name] = SecurityMonitor({}, logger)
    return _modules_cache[name]


# ---- Tool handlers ----

def _scan_network() -> dict:
    return _get_module("network").scan()


def _scan_processes() -> dict:
    return _get_module("process").scan()


def _check_firewall() -> dict:
    return _get_module("firewall").check()


def _read_security_logs(minutes_back: int = 30) -> dict:
    events = _get_module("security").collect_events()
    # Filter by time window
    cutoff = None
    if minutes_back > 0:
        from datetime import datetime, timedelta
        cutoff = datetime.now() - timedelta(minutes=minutes_back)
    if cutoff:
        events = [e for e in events if _parse_event_time(e) >= cutoff]
    return {"events": events[-50:], "count": len(events),
            "minutes_back": minutes_back}


def _parse_event_time(event: dict):
    from datetime import datetime
    try:
        return datetime.strptime(event.get("time", ""), "%Y-%m-%d %H:%M:%S")
    except (ValueError, KeyError):
        return datetime.min


def _security_summary() -> dict:
    return _get_module("security").get_summary()


def _get_system_state() -> dict:
    import psutil
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.5),
        "memory_percent": psutil.virtual_memory().percent,
        "memory_used_gb": round(psutil.virtual_memory().used / (1024**3), 1),
        "memory_total_gb": round(psutil.virtual_memory().total / (1024**3), 1),
        "disk_percent": psutil.disk_usage("C:\\").percent,
        "boot_time": psutil.boot_time(),
        "hostname": subprocess.run("hostname", capture_output=True, text=True,
                                   shell=True, encoding="utf-8", errors="replace").stdout.strip(),
    }


def _get_listening_ports() -> dict:
    try:
        ports = _get_module("network").get_listening_ports()
        return {"ports": ports, "count": len(ports)}
    except Exception as e:
        return {"error": str(e)}


def _run_command(command: str, timeout: int = 15) -> dict:
    """Execute a command in the secure sandbox."""
    sandbox = get_sandbox()
    result = sandbox.execute(command, timeout=timeout)
    return result


def _check_command(command: str) -> dict:
    """Check if a command is allowed without executing it."""
    sandbox = get_sandbox()
    return sandbox.quick_check(command)


# ================================================================
#  Build default registry
# ================================================================

def create_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()

    registry.register(ToolDef(
        name="scan_network",
        description="Scan active network connections. Detects suspicious IPs, "
                    "malicious ports (Metasploit:4444, Back Orifice:31337, C2, "
                    "backdoors), and high-frequency connections. "
                    "Returns status (normal/suspicious/under_attack), "
                    "suspicious IP count, and detailed findings.",
        parameters={},
        handler=_scan_network,
    ))

    registry.register(ToolDef(
        name="scan_processes",
        description="Scan running processes for suspicious names and high resource "
                    "usage. Checks for known hacker tools (mimikatz, nmap, cobalt, "
                    "etc.) and processes exceeding CPU/memory thresholds.",
        parameters={},
        handler=_scan_processes,
    ))

    registry.register(ToolDef(
        name="check_firewall",
        description="Check Windows Firewall and Defender status. "
                    "Returns whether firewall is enabled per profile and "
                    "whether Defender real-time protection is active.",
        parameters={},
        handler=_check_firewall,
    ))

    registry.register(ToolDef(
        name="read_security_logs",
        description="Read Windows security event logs. Looks for login failures "
                    "(4625), privilege changes (4672), new user creation (4720), "
                    "and other suspicious events.",
        parameters={
            "minutes_back": {
                "type": "integer",
                "description": "How many minutes back to read logs (default 30)",
                "default": 30,
            },
        },
        handler=_read_security_logs,
    ))

    registry.register(ToolDef(
        name="security_summary",
        description="Get a summary of recent security events including failed "
                    "logins, new processes, new users, and overall risk level.",
        parameters={},
        handler=_security_summary,
    ))

    registry.register(ToolDef(
        name="get_system_state",
        description="Get current system resource metrics: CPU usage, memory usage, "
                    "disk usage, and uptime.",
        parameters={},
        handler=_get_system_state,
    ))

    registry.register(ToolDef(
        name="get_listening_ports",
        description="List all open TCP listening ports on the local system.",
        parameters={},
        handler=_get_listening_ports,
    ))

    registry.register(ToolDef(
        name="run_command",
        description="Execute a safe Windows diagnostic command inside a secure "
                    "sandbox (Job Object isolation, memory limit, timeout, "
                    "desktop isolation, audit logging). "
                    "Completely safe commands only: ipconfig, netstat, tasklist, "
                    "systeminfo, ping, nslookup, sc query, etc. "
                    "Blocked: destructive commands, pipes, redirects, admin operations.",
        parameters={
            "command": {
                "type": "string",
                "description": "The command to execute",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default 15)",
                "default": 15,
            },
        },
        handler=_run_command,
        require_admin=False,
    ))

    registry.register(ToolDef(
        name="check_command",
        description="Check if a shell command is allowed by the security sandbox "
                    "without executing it. Returns whether the command would be "
                    "allowed or blocked, and the reason.",
        parameters={
            "command": {
                "type": "string",
                "description": "The command to validate",
            },
        },
        handler=_check_command,
    ))

    # ---- Threat Intelligence (AlienVault OTX) ----

    registry.register(ToolDef(
        name="threat_check_ip",
        description="Check IP address reputation using AlienVault OTX threat "
                    "intelligence. Returns: reputation score, pulse count, "
                    "country/city, malicious flag, threat tags, and recent "
                    "threat pulse summaries. Free, no API key needed.",
        parameters={
            "ip": {
                "type": "string",
                "description": "IPv4 address to check (e.g., 45.155.205.233)",
            },
        },
        handler=threat_check_ip,
    ))

    registry.register(ToolDef(
        name="threat_check_domain",
        description="Check domain reputation using AlienVault OTX. Returns: "
                    "reputation score, pulse count, Alexa rank, WHOIS info, "
                    "malicious flag, and threat tags.",
        parameters={
            "domain": {
                "type": "string",
                "description": "Domain name to check (e.g., evil.com)",
            },
        },
        handler=threat_check_domain,
    ))

    registry.register(ToolDef(
        name="threat_check_hash",
        description="Check file hash (MD5/SHA1/SHA256) reputation using "
                    "AlienVault OTX. Returns: malware name, file type, "
                    "reputation score, and threat tags.",
        parameters={
            "file_hash": {
                "type": "string",
                "description": "File hash to check (MD5/SHA1/SHA256)",
            },
        },
        handler=threat_check_hash,
    ))

    registry.register(ToolDef(
        name="threat_pulse_search",
        description="Search AlienVault OTX threat pulses by keyword (e.g., "
                    "ransomware, CVE-2024, APT28). Returns matching threat "
                    "intelligence reports with descriptions and tags.",
        parameters={
            "query": {
                "type": "string",
                "description": "Search keyword (ransomware, CVE, APT, etc.)",
            },
        },
        handler=threat_pulse_search,
    ))

    # ---- Windows Defender (built-in antivirus) ----

    registry.register(ToolDef(
        name="defender_status",
        description="Get Windows Defender status: real-time protection, "
                    "antivirus/spyware engine state, last scan times, "
                    "signature version. Free, no API key, built into Windows.",
        parameters={},
        handler=defender_status,
    ))

    registry.register(ToolDef(
        name="defender_quick_scan",
        description="Start a Windows Defender quick scan of critical system "
                    "areas. Returns immediately; check defender_threat_list "
                    "for results after a few minutes.",
        parameters={},
        handler=defender_quick_scan,
    ))

    registry.register(ToolDef(
        name="defender_full_scan",
        description="Start a full Windows Defender scan of the entire system. "
                    "Warning: may take hours. Check defender_threat_list later.",
        parameters={},
        handler=defender_full_scan,
    ))

    registry.register(ToolDef(
        name="defender_threat_list",
        description="List all threats detected by Windows Defender: malware "
                    "name, severity, detection time, action taken, and "
                    "affected files. Use after triggering a scan.",
        parameters={},
        handler=defender_threat_list,
    ))

    registry.register(ToolDef(
        name="defender_update",
        description="Update Windows Defender virus signatures to the latest "
                    "version. Run before a scan to ensure up-to-date detection.",
        parameters={},
        handler=defender_update_signatures,
    ))

    # ---- NVD Vulnerability Database ----

    registry.register(ToolDef(
        name="cve_lookup",
        description="Look up a CVE vulnerability by ID (e.g., CVE-2024-1234). "
                    "Returns: severity (NONE/LOW/MEDIUM/HIGH/CRITICAL), "
                    "CVSS score, description, exploitability, references. "
                    "Uses NIST NVD — free, no API key.",
        parameters={
            "cve_id": {
                "type": "string",
                "description": "CVE ID to look up, e.g. CVE-2024-1234",
            },
        },
        handler=nvd_cve_lookup,
    ))

    registry.register(ToolDef(
        name="cve_search",
        description="Search for CVEs by keyword (e.g., 'Windows 11', "
                    "'Apache Log4j', 'Chrome'). Returns top matching "
                    "vulnerabilities with severity and CVSS scores.",
        parameters={
            "keyword": {
                "type": "string",
                "description": "Keyword to search, e.g. 'Exchange Server'",
            },
            "limit": {
                "type": "integer",
                "description": "Max results (default 10, max 20)",
                "default": 10,
            },
        },
        handler=nvd_cve_search,
    ))

    # ---- Web Search & Fetch ----

    registry.register(ToolDef(
        name="web_search",
        description="Search the web using DuckDuckGo. Free, no API key. "
                    "Use to find MCP servers, security tools, CVE details, "
                    "or documentation. Returns title + URL for each result.",
        parameters={
            "query": {
                "type": "string",
                "description": "Search query",
            },
            "max_results": {
                "type": "integer",
                "description": "Max results (default 5)",
                "default": 5,
            },
        },
        handler=web_search,
    ))

    registry.register(ToolDef(
        name="web_fetch",
        description="Fetch a web page as plain text. Use to read "
                    "documentation, API references, or tool descriptions. "
                    "Limited to 8KB output. Safe: only reads HTML.",
        parameters={
            "url": {
                "type": "string",
                "description": "URL to fetch",
            },
        },
        handler=web_fetch,
    ))

    # ---- Self-Install (sandboxed) ----

    registry.register(ToolDef(
        name="install_skill",
        description="Install a new skill by writing a .md file to skills/. "
                    "SAFE: Skills are markdown text injected into the prompt, "
                    "NEVER executed as code. Content is sanitized — code "
                    "injection patterns (os.system, subprocess, exec, eval, "
                    "rm -rf, del /f, format, shutdown) are rejected.",
        parameters={
            "name": {
                "type": "string",
                "description": "Skill name (a-z, 0-9, -, _ only)",
            },
            "description": {
                "type": "string",
                "description": "One-line description of what this skill does",
            },
            "content": {
                "type": "string",
                "description": "Markdown instructions for the skill",
            },
            "triggers": {
                "type": "string",
                "description": "Comma-separated trigger phrases, e.g. 'scan,audit,check'",
            },
        },
        handler=install_skill,
    ))

    registry.register(ToolDef(
        name="recommend_mcp_server",
        description="Recommend an MCP server to install. DOES NOT auto-install "
                    "(MCP servers can execute arbitrary code — user must "
                    "manually review and add to config.yaml). Returns the "
                    "exact config snippet to add.",
        parameters={
            "name": {
                "type": "string",
                "description": "Name for this MCP server",
            },
            "install_command": {
                "type": "string",
                "description": "Command to run the MCP server, e.g. 'npx @anthropic/mcp-server-filesystem /path'",
            },
            "description": {
                "type": "string",
                "description": "What this MCP server provides",
            },
        },
        handler=recommend_mcp_server,
    ))

    registry.register(ToolDef(
        name="list_skills",
        description="List all currently installed skills in the skills/ directory.",
        parameters={},
        handler=list_installed_skills,
    ))

    return registry
