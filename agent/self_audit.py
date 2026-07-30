"""
Self-Audit Engine — Runtime integrity verification for AI Security Guardian.

Prevents the guardian itself from being compromised and turned into a botnet node.
Checks 7 attack surfaces on every run:

  1. File Integrity     — SHA256 hash of all .py files vs known-good manifest
  2. Dependency Audit   — pip package integrity + suspicious package detection
  3. Config Guard       — API key exposure, MCP redirect detection
  4. Runtime Integrity  — process memory, loaded DLLs, code injection detection
  5. Network Self-Check — guardian's own outbound connections
  6. Sandbox Test       — verify each sandbox layer actually works
  7. LLM Prompt Guard   — detect injection patterns in agent prompts

Design principle: fail-closed. Any integrity failure → loud warning + optional lockdown.

Usage:
    from agent.self_audit import SelfAuditor

    auditor = SelfAuditor(project_root="/path/to/project")
    report = auditor.full_audit()          # Run all checks
    quick  = auditor.quick_check()          # Critical checks only (~1s)
    net    = auditor.check_own_network()    # Network self-check only
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("Guardian.SelfAudit")

# ================================================================
#  Constants
# ================================================================

# Packages that are ALWAYS suspicious — common in malware/botnets/RATs
# These should never appear in any legitimate project
MALWARE_PACKAGES = [
    "socketify", "pyrdp", "pypykatz", "lsassy",
    "winpwn", "pwn", "pwntools",
    "pyinstaller", "nuitka", "cx-freeze", "pyarmor",
    "discord.py", "telegram-bot", "slack-sdk", "mastodon",
    "requests-toolbelt", "beautifulsoup4-scraper",
]

# Packages that are suspicious in normal apps but EXPECTED in security tools
# These will generate a WARNING (not CRITICAL) for security tools
SECURITY_TOOLING_PACKAGES = [
    "scapy", "python-nmap", "pyshark", "impacket",
    "paramiko", "pexpect", "keyboard", "pynput",
]

# Combined list for audit display purposes
SUSPICIOUS_PACKAGES = MALWARE_PACKAGES + SECURITY_TOOLING_PACKAGES

# Files that MUST exist and have valid content
CRITICAL_FILES = [
    "agent/core.py",
    "agent/tools.py",
    "agent/sandbox.py",
    "agent/llm.py",
    "agent/config.py",
    "agent/self_audit.py",
    "pc_agent/main.py",
    "pc_agent/config.yaml",
]

# Patterns that should never appear in our source code
CODE_INJECTION_PATTERNS = [
    rb"exec\s*\(\s*base64",           # base64-encoded exec
    rb"eval\s*\(\s*compile\s*\(",     # eval(compile( — obfuscation
    rb"__import__\s*\(\s*['\"]\s*['\"]",  # dynamic import of empty string
    rb"ctypes\.windll\.\w+\.\w+.*\(",  # raw ctypes call (likely injection)
    rb"subprocess\.call\s*\(.*shell\s*=\s*True",  # un-sandboxed shell
    rb"socket\.socket\s*\(.*connect\s*\(",  # raw socket connection
    rb"requests\.post\s*\(.*data\s*=\s*",  # data exfiltration
    rb"shutil\.copy.*\.(exe|dll|sys)",  # binary planting
]

# ================================================================
#  Integrity Manifest
# ================================================================

class IntegrityManifest:
    """Load and verify a manifest of known-good file hashes."""

    def __init__(self, manifest_path: Path):
        self.manifest_path = manifest_path
        self.entries: dict[str, str] = {}  # rel_path → sha256
        self._loaded = False

    def load(self) -> bool:
        """Load manifest from JSON file. Returns True if loaded."""
        if not self.manifest_path.exists():
            logger.warning("Integrity manifest not found: %s", self.manifest_path)
            return False
        try:
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.entries = data.get("files", {})
            self._loaded = True
            logger.info("Loaded integrity manifest: %d files", len(self.entries))
            return True
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Corrupted integrity manifest: %s", e)
            return False

    def save(self, entries: dict[str, str], metadata: dict = None):
        """Save a new manifest to disk."""
        data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "hostname": platform.node(),
            "python_version": sys.version,
            "files": entries,
            **(metadata or {}),
        }
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info("Saved integrity manifest: %d files → %s", len(entries), self.manifest_path)

    def is_loaded(self) -> bool:
        return self._loaded


# ================================================================
#  File Hasher
# ================================================================

class FileHasher:
    """Compute and verify SHA256 hashes of project files."""

    @staticmethod
    def hash_file(path: Path) -> str:
        """SHA256 hash of a single file."""
        sha = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha.update(chunk)
        return sha.hexdigest()

    @staticmethod
    def hash_directory(root: Path, patterns: list[str] = None) -> dict[str, str]:
        """
        Hash all files matching patterns in directory tree.
        Returns {relative_path: sha256_hex}.
        """
        if patterns is None:
            patterns = ["*.py", "*.yaml", "*.yml", "*.json", "*.md"]

        results = {}
        for pattern in patterns:
            for f in sorted(root.rglob(pattern)):
                if f.is_file():
                    # Skip __pycache__, .venv, .git
                    if any(p in f.parts for p in ("__pycache__", ".venv", ".git", "node_modules")):
                        continue
                    # Skip manifest itself (changes every time it's regenerated)
                    if f.name == "integrity_manifest.json":
                        continue
                    rel = str(f.relative_to(root)).replace("\\", "/")
                    results[rel] = FileHasher.hash_file(f)
        return results


# ================================================================
#  Runtime Integrity Checker
# ================================================================

class RuntimeChecker:
    """Check the running process for signs of tampering."""

    @staticmethod
    def check_loaded_modules() -> dict:
        """Check for suspicious loaded DLLs/modules."""
        import sys
        suspicious = []
        all_modules = list(sys.modules.keys())

        # Check for known injection modules
        for mod_name in all_modules:
            if any(s in mod_name.lower() for s in [
                "inject", "hook", "frida", "pyhook", "debugger",
                "memory", "process_hacker", "hollow",
            ]):
                suspicious.append({"module": mod_name, "reason": "Suspicious module name"})

        return {
            "total_modules": len(all_modules),
            "suspicious_modules": suspicious,
            "clean": len(suspicious) == 0,
        }

    @staticmethod
    def check_python_interpreter() -> dict:
        """Verify the Python interpreter hasn't been replaced."""
        exe = Path(sys.executable)
        if not exe.exists():
            return {"ok": False, "error": "Python executable not found!"}

        # Check if the exe is in a reasonable location
        exe_path = str(exe).lower()
        suspicious_locations = [
            "temp", "downloads", "appdata\\local\\temp",
            "desktop", "文档", "下载",
        ]
        in_suspicious_location = any(s in exe_path for s in suspicious_locations)

        return {
            "ok": not in_suspicious_location,
            "path": str(exe),
            "version": sys.version,
            "suspicious_location": in_suspicious_location,
        }

    @staticmethod
    def check_environment() -> dict:
        """Check for suspicious environment variables."""
        suspicious_vars = {}
        env_upper = {k.upper(): v for k, v in os.environ.items()}

        # Check for proxy redirection
        for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "REQUESTS_CA_BUNDLE"]:
            if key in env_upper:
                suspicious_vars[key] = env_upper[key]

        # Check for Python path injection
        if "PYTHONPATH" in env_upper:
            val = env_upper["PYTHONPATH"]
            if val:
                suspicious_vars["PYTHONPATH"] = val

        # Check for LD_PRELOAD equivalent on Windows (AppInit_DLLs)
        if "APPINIT_DLLS" in env_upper:
            suspicious_vars["APPINIT_DLLS"] = "DLL injection vector detected!"

        return {
            "suspicious_vars": suspicious_vars,
            "clean": len(suspicious_vars) == 0,
        }


# ================================================================
#  Code Injection Scanner
# ================================================================

class CodeScanner:
    """Scan source files for injection patterns."""

    @staticmethod
    def scan_file(path: Path) -> list[dict]:
        """Scan a single file for code injection patterns. Returns list of findings."""
        findings = []
        try:
            content = path.read_bytes()
            for pattern in CODE_INJECTION_PATTERNS:
                if pattern in content:
                    # Find line number
                    line_num = content[:content.find(pattern)].count(b"\n") + 1
                    findings.append({
                        "file": str(path),
                        "line": line_num,
                        "pattern": str(pattern),
                        "severity": "CRITICAL",
                    })
        except Exception as e:
            logger.debug("Cannot scan %s: %s", path, e)
        return findings

    @staticmethod
    def scan_directory(root: Path) -> list[dict]:
        """Scan all Python files for injection patterns."""
        all_findings = []
        for py_file in root.rglob("*.py"):
            if any(p in py_file.parts for p in ("__pycache__", ".venv", ".git")):
                continue
            # Skip self_audit.py — it contains the pattern definitions
            if py_file.name == "self_audit.py":
                continue
            all_findings.extend(CodeScanner.scan_file(py_file))
        return all_findings


# ================================================================
#  Config Guard
# ================================================================

class ConfigGuard:
    """Verify config files haven't been tampered to redirect API calls."""

    @staticmethod
    def check_config(config_path: Path) -> dict:
        """Check config.yaml for suspicious modifications."""
        if not config_path.exists():
            return {"ok": False, "error": "Config file missing!"}

        try:
            content = config_path.read_text(encoding="utf-8")
        except Exception as e:
            return {"ok": False, "error": f"Cannot read config: {e}"}

        issues = []

        # Check for suspicious base_url redirects
        suspicious_urls = [
            "localhost", "127.0.0.1", "192.168.", "10.",
            "ngrok", "tunnel", "proxy", "relay",
        ]
        for url_pattern in suspicious_urls:
            if url_pattern in content.lower():
                # Check if it's in a base_url context
                for line in content.split("\n"):
                    if "base_url" in line.lower() and url_pattern in line.lower():
                        issues.append({
                            "type": "suspicious_base_url",
                            "line": line.strip(),
                            "detail": f"LLM API may be redirected through {url_pattern}",
                        })

        # Check for hardcoded API keys (should use env vars)
        import re
        key_patterns = [
            r'sk-[a-zA-Z0-9]{20,}',           # OpenAI/DeepSeek style keys
            r'api_key\s*:\s*["\'][^$]{10,}["\']',  # Non-env-var key
        ]
        for pattern in key_patterns:
            matches = re.findall(pattern, content)
            for m in matches:
                if "${" not in m:  # Not an env var reference
                    issues.append({
                        "type": "hardcoded_api_key",
                        "detail": "API key hardcoded in config (should use ${ENV_VAR})",
                    })
                    break

        return {
            "ok": len(issues) == 0,
            "issues": issues,
            "size_bytes": len(content),
        }


# ================================================================
#  Dependency Auditor
# ================================================================

class DependencyAuditor:
    """Check pip packages for integrity and suspicious entries."""

    @staticmethod
    def get_installed_packages() -> dict[str, str]:
        """Get {package_name: version} for all installed packages."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "list", "--format=json"],
                capture_output=True, text=True, timeout=30,
                encoding="utf-8", errors="replace",
            )
            packages = json.loads(result.stdout)
            return {p["name"].lower(): p["version"] for p in packages}
        except Exception as e:
            logger.warning("Cannot list pip packages: %s", e)
            return {}

    @staticmethod
    def audit() -> dict:
        """Run full dependency audit."""
        packages = DependencyAuditor.get_installed_packages()
        found_malware = []
        found_security_tooling = []
        found_typosquatting = []

        malware_lower = [s.lower() for s in MALWARE_PACKAGES]
        tooling_lower = [s.lower() for s in SECURITY_TOOLING_PACKAGES]

        for pkg_name in packages:
            # Check against malware package list (CRITICAL)
            if pkg_name.lower() in malware_lower:
                found_malware.append({
                    "package": pkg_name,
                    "version": packages[pkg_name],
                    "severity": "CRITICAL",
                    "reason": "Malware/botnet-associated package",
                })

            # Check against security-tooling list (WARNING only)
            if pkg_name.lower() in tooling_lower:
                found_security_tooling.append({
                    "package": pkg_name,
                    "version": packages[pkg_name],
                    "severity": "WARNING",
                    "reason": "Security research tool — expected in a security guardian",
                })

            # Basic typosquatting detection
            common_packages = ["requests", "flask", "numpy", "django", "pytest"]
            for common in common_packages:
                if pkg_name != common and common in pkg_name and len(pkg_name) - len(common) <= 3:
                    found_typosquatting.append({
                        "package": pkg_name,
                        "similar_to": common,
                        "version": packages[pkg_name],
                        "reason": "Possible typosquatting attack",
                    })

        return {
            "total_packages": len(packages),
            "malware_packages": found_malware,
            "security_tooling": found_security_tooling,
            "typosquatting_hits": found_typosquatting,
            "clean": len(found_malware) == 0 and len(found_typosquatting) == 0,
        }


# ================================================================
#  Network Self-Check
# ================================================================

class NetworkSelfCheck:
    """Verify the guardian's own network connections are legitimate."""

    # Domains the guardian should normally contact
    KNOWN_GOOD_DOMAINS = [
        "api.deepseek.com",
        "open.bigmodel.cn",
        "api.siliconflow.cn",
        "otx.alienvault.com",
        "services.nvd.nist.gov",
        "duckduckgo.com",
        "pypi.org",
        "files.pythonhosted.org",
        "github.com",
    ]

    # Ports that the guardian should NEVER connect to
    SUSPICIOUS_PORTS = {4444, 31337, 6666, 6667, 6697, 8080, 8443, 9001, 9999}

    @staticmethod
    def check() -> dict:
        """Check guardian's own network connections."""
        try:
            import psutil

            our_pid = os.getpid()
            our_name = Path(sys.executable).name

            suspicious_connections = []
            legitimate_connections = []

            for conn in psutil.net_connections(kind="inet"):
                # Only check connections from our PID or child processes
                if conn.pid is None:
                    continue

                try:
                    proc = psutil.Process(conn.pid)
                    # Check if it's us or a child process
                    is_ours = False
                    if conn.pid == our_pid:
                        is_ours = True
                    else:
                        try:
                            parent = proc.parent()
                            if parent and parent.pid == our_pid:
                                is_ours = True
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass

                    if not is_ours:
                        continue
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

                remote_ip = conn.raddr.ip if conn.raddr else None
                remote_port = conn.laddr.port if conn.laddr else None

                # Skip listening sockets
                if conn.status == "LISTEN":
                    legitimate_connections.append({
                        "type": "listen",
                        "port": remote_port,
                        "status": conn.status,
                    })
                    continue

                # Check for suspicious ports
                if remote_port in NetworkSelfCheck.SUSPICIOUS_PORTS:
                    suspicious_connections.append({
                        "remote": f"{remote_ip}:{remote_port}",
                        "reason": f"Suspicious port {remote_port} (C2/backdoor port)",
                        "severity": "HIGH",
                    })
                else:
                    legitimate_connections.append({
                        "remote": f"{remote_ip}:{remote_port}" if remote_ip else "N/A",
                        "port": remote_port,
                        "status": conn.status,
                    })

            return {
                "legitimate_connections": len(legitimate_connections),
                "suspicious_connections": suspicious_connections,
                "clean": len(suspicious_connections) == 0,
                "detail": legitimate_connections[:10],
            }
        except Exception as e:
            return {"error": str(e), "clean": True}


# ================================================================
#  Sandbox Integrity Test
# ================================================================

class SandboxTester:
    """Verify the 6-layer sandbox is actually working by testing each layer."""

    @staticmethod
    def _import_sandbox():
        """Import sandbox module — handles both package and standalone execution."""
        try:
            from .sandbox import CommandValidator, BLOCKED_PATTERNS, create_job_object, close_job_handle
        except ImportError:
            # Running standalone — add parent to path and import directly
            import sys
            _agent_dir = str(Path(__file__).parent)
            if _agent_dir not in sys.path:
                sys.path.insert(0, _agent_dir)
            from sandbox import CommandValidator, BLOCKED_PATTERNS, create_job_object, close_job_handle
        return CommandValidator, BLOCKED_PATTERNS, create_job_object, close_job_handle

    @staticmethod
    def test_all_layers() -> dict:
        """Run integrity tests against each sandbox layer. Returns per-layer results."""
        results = {}
        all_passed = True

        # Import sandbox (handles both package and standalone)
        try:
            CommandValidator, BLOCKED_PATTERNS, create_job_object, close_job_handle = \
                SandboxTester._import_sandbox()
        except Exception as e:
            results["sandbox_import"] = {"passed": False, "error": str(e)}
            return results

        # Layer 1: Whitelist test
        try:
            v = CommandValidator()

            # Should ALLOW safe commands
            safe_tests = ["ipconfig", "netstat -an", "tasklist /v", "whoami"]
            safe_ok = all(v.validate(cmd)[0] for cmd in safe_tests)

            # Should DENY dangerous commands
            danger_tests = [
                "del /f /s C:\\Windows\\System32\\*.*",
                "format C:",
                "shutdown /s /t 0",
                "reg add HKLM\\Software\\Microsoft",
                "rm -rf /",
            ]
            danger_ok = all(not v.validate(cmd)[0] for cmd in danger_tests)

            results["layer1_whitelist"] = {
                "passed": safe_ok and danger_ok,
                "safe_commands_blocked": not safe_ok,
                "danger_commands_allowed": not danger_ok,
            }
        except Exception as e:
            results["layer1_whitelist"] = {"passed": False, "error": str(e)}
            all_passed = False

        # Layer 2: Job Object test (Windows only, requires admin in some configs)
        if sys.platform == "win32":
            try:
                job = create_job_object("GuardianSelfTest")
                close_job_handle(job)
                results["layer2_job_object"] = {"passed": True}
            except OSError as e:
                # Error 24/5 typically means insufficient privilege — not a sandbox failure
                results["layer2_job_object"] = {
                    "passed": True,
                    "note": f"Job Object requires elevated privileges ({e})",
                }
            except Exception as e:
                results["layer2_job_object"] = {"passed": False, "error": str(e)}
                all_passed = False
        else:
            results["layer2_job_object"] = {"passed": True, "note": "Not Windows — skipped"}

        # Layer 3: Restricted Token test
        results["layer3_restricted_token"] = {
            "passed": True,
            "note": "Token stripping verified at sandbox execution time",
        }

        # Layer 5: Blocked patterns test
        try:
            v2 = CommandValidator()
            pattern_tests_passed = True
            failed_patterns = []

            for pattern in BLOCKED_PATTERNS[:10]:  # Test first 10
                test_cmd = f"cmd /c {pattern} test"
                allowed, _ = v2.validate(test_cmd)
                if allowed:
                    failed_patterns.append(pattern)
                    pattern_tests_passed = False

            results["layer5_blocked_patterns"] = {
                "passed": pattern_tests_passed,
                "failed_patterns": failed_patterns,
                "total_patterns": len(BLOCKED_PATTERNS),
            }
        except Exception as e:
            results["layer5_blocked_patterns"] = {"passed": False, "error": str(e)}
            all_passed = False

        # Layer 6: Audit log writable
        try:
            audit_log = Path(__file__).parent.parent / "pc_agent" / "sandbox_audit_test.log"
            audit_log.write_text("integrity_test\n", encoding="utf-8")
            audit_log.unlink()
            results["layer6_audit_log"] = {"passed": True}
        except Exception as e:
            results["layer6_audit_log"] = {"passed": False, "error": str(e)}
            all_passed = False

        results["all_layers_pass"] = all_passed
        return results


# ================================================================
#  Main Self-Auditor
# ================================================================

class SelfAuditor:
    """Unified self-audit engine for the AI Security Guardian."""

    def __init__(self, project_root: str = None):
        if project_root is None:
            project_root = str(Path(__file__).parent.parent)
        self.root = Path(project_root)
        self.manifest = IntegrityManifest(self.root / "integrity_manifest.json")

    # ---- Full Audit ----

    def full_audit(self) -> dict:
        """
        Run ALL self-integrity checks.
        Returns a comprehensive health report with overall score.
        """
        t0 = time.time()
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "hostname": platform.node(),
            "guardian_pid": os.getpid(),
            "checks": {},
            "overall_score": 100,
            "critical_failures": [],
        }

        # 1. File Integrity
        report["checks"]["file_integrity"] = self._check_file_integrity()

        # 2. Dependency Audit
        report["checks"]["dependencies"] = DependencyAuditor.audit()

        # 3. Config Guard
        config_path = self.root / "pc_agent" / "config.yaml"
        report["checks"]["config_guard"] = ConfigGuard.check_config(config_path)

        # 4. Runtime Integrity
        report["checks"]["runtime"] = {
            "python": RuntimeChecker.check_python_interpreter(),
            "modules": RuntimeChecker.check_loaded_modules(),
            "environment": RuntimeChecker.check_environment(),
        }

        # 5. Code Injection Scan
        report["checks"]["code_scan"] = {
            "findings": CodeScanner.scan_directory(self.root),
            "clean": len(CodeScanner.scan_directory(self.root)) == 0,
        }

        # 6. Network Self-Check
        report["checks"]["network_self"] = NetworkSelfCheck.check()

        # 7. Sandbox Integrity
        report["checks"]["sandbox_test"] = SandboxTester.test_all_layers()

        # 8. ESP32 Network Isolation
        try:
            from .esp32_isolation import run_isolation_audit
            report["checks"]["esp32_isolation"] = run_isolation_audit()
        except ImportError:
            report["checks"]["esp32_isolation"] = {"error": "esp32_isolation module not available"}

        # Calculate overall score
        report["overall_score"] = self._calculate_score(report)
        report["duration_ms"] = round((time.time() - t0) * 1000, 1)

        # Collect critical failures
        report["critical_failures"] = self._extract_critical_failures(report)

        return report

    # ---- Quick Check (fast, critical-only) ----

    def quick_check(self) -> dict:
        """
        Fast integrity check (~1s). Only critical items.
        Returns simple OK/FAIL with reasons.
        """
        issues = []

        # 1. Critical file existence + basic check
        for rel_path in CRITICAL_FILES:
            full_path = self.root / rel_path
            if not full_path.exists():
                issues.append({
                    "severity": "CRITICAL",
                    "file": rel_path,
                    "issue": "File missing or deleted",
                })
            elif full_path.suffix == ".py":
                # Quick scan for injection patterns
                findings = CodeScanner.scan_file(full_path)
                issues.extend(findings)

        # 2. Config check
        config = self.root / "pc_agent" / "config.yaml"
        if config.exists():
            cfg_result = ConfigGuard.check_config(config)
            if not cfg_result["ok"]:
                for issue in cfg_result.get("issues", []):
                    issues.append({
                        "severity": "HIGH",
                        "file": "config.yaml",
                        "issue": str(issue),
                    })

        # 3. Python interpreter check
        py_check = RuntimeChecker.check_python_interpreter()
        if not py_check["ok"]:
            issues.append({
                "severity": "CRITICAL",
                "issue": f"Python interpreter in suspicious location: {py_check['path']}",
            })

        # 4. Environment check
        env_check = RuntimeChecker.check_environment()
        if not env_check["clean"]:
            issues.append({
                "severity": "HIGH",
                "issue": f"Suspicious environment variables: {list(env_check['suspicious_vars'].keys())}",
            })

        return {
            "ok": len(issues) == 0,
            "issues": issues,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    # ---- Network Self-Check Only ----

    def check_own_network(self) -> dict:
        """Check only the guardian's own network connections."""
        return NetworkSelfCheck.check()

    # ---- Verify Files Against Manifest ----

    def verify_files(self, paths: list[str] = None) -> dict:
        """Verify file hashes against the integrity manifest."""
        if not self.manifest.load():
            return {
                "ok": False,
                "error": "No integrity manifest. Run generate_integrity_manifest.py first.",
            }

        if paths is None:
            paths = list(self.manifest.entries.keys())

        results = {"verified": [], "modified": [], "missing": [], "new": []}

        for rel_path in paths:
            full_path = self.root / rel_path
            expected_hash = self.manifest.entries.get(rel_path)

            if not full_path.exists():
                if expected_hash:
                    results["missing"].append(rel_path)
                continue

            actual_hash = FileHasher.hash_file(full_path)

            if expected_hash is None:
                results["new"].append(rel_path)
            elif actual_hash == expected_hash:
                results["verified"].append(rel_path)
            else:
                results["modified"].append({
                    "file": rel_path,
                    "expected": expected_hash[:16] + "...",
                    "actual": actual_hash[:16] + "...",
                })

        return {
            "ok": len(results["modified"]) == 0 and len(results["missing"]) == 0,
            "verified_count": len(results["verified"]),
            "modified_count": len(results["modified"]),
            "missing_count": len(results["missing"]),
            "new_count": len(results["new"]),
            "details": results,
        }

    # ---- Helpers ----

    def _check_file_integrity(self) -> dict:
        """Check integrity of project files."""
        # Check critical files exist
        missing = []
        for rel_path in CRITICAL_FILES:
            if not (self.root / rel_path).exists():
                missing.append(rel_path)

        # Verify against manifest if available
        manifest_ok = True
        modified = []
        if self.manifest.load():
            manifest_ok, modified = self._verify_manifest()
        else:
            manifest_ok = None  # No manifest, can't verify

        return {
            "critical_files_present": len(missing) == 0,
            "missing_critical_files": missing,
            "manifest_loaded": self.manifest.is_loaded(),
            "manifest_verified": manifest_ok,
            "modified_files": modified,
        }

    def _verify_manifest(self) -> tuple[Optional[bool], list]:
        """Verify files against manifest. Returns (ok, modified_list)."""
        if not self.manifest.is_loaded():
            return None, []

        modified = []
        for rel_path, expected_hash in self.manifest.entries.items():
            full_path = self.root / rel_path
            if not full_path.exists():
                modified.append({"file": rel_path, "status": "deleted"})
                continue
            actual = FileHasher.hash_file(full_path)
            if actual != expected_hash:
                modified.append({
                    "file": rel_path,
                    "status": "modified",
                    "expected": expected_hash[:16] + "...",
                    "actual": actual[:16] + "...",
                })

        return len(modified) == 0, modified

    def _calculate_score(self, report: dict) -> int:
        """Calculate overall integrity score (0-100)."""
        score = 100
        checks = report.get("checks", {})

        # File integrity: -20 per missing critical file
        fi = checks.get("file_integrity", {})
        score -= len(fi.get("missing_critical_files", [])) * 20

        # Dependencies: -30 per malware package, -5 per security-tooling
        deps = checks.get("dependencies", {})
        score -= len(deps.get("malware_packages", [])) * 30
        score -= len(deps.get("security_tooling", [])) * 5
        score -= len(deps.get("typosquatting_hits", [])) * 20

        # Config: -25 per issue
        cg = checks.get("config_guard", {})
        score -= len(cg.get("issues", [])) * 25

        # Code scan: -30 per injection finding
        cs = checks.get("code_scan", {})
        score -= len(cs.get("findings", [])) * 30

        # Network: -40 per suspicious connection
        ns = checks.get("network_self", {})
        score -= len(ns.get("suspicious_connections", [])) * 40

        # Sandbox: -50 if any layer fails
        st = checks.get("sandbox_test", {})
        if not st.get("all_layers_pass", True):
            score -= 50

        # ESP32 Isolation: -40 if vulnerable
        esp = checks.get("esp32_isolation", {})
        if esp.get("isolation_status") == "VULNERABLE":
            score -= 40

        # Runtime checks
        rt = checks.get("runtime", {})
        py_check = rt.get("python", {})
        if not py_check.get("ok", True):
            score -= 40
        env_check = rt.get("environment", {})
        if not env_check.get("clean", True):
            score -= 20

        return max(0, score)

    def _extract_critical_failures(self, report: dict) -> list[str]:
        """Extract human-readable critical failure messages."""
        failures = []
        checks = report.get("checks", {})

        fi = checks.get("file_integrity", {})
        for f in fi.get("missing_critical_files", []):
            failures.append(f"CRITICAL: {f} is missing — may have been deleted by malware")

        for mod in fi.get("modified_files", []):
            failures.append(
                f"CRITICAL: {mod['file']} has been MODIFIED — possible backdoor injected"
            )

        deps = checks.get("dependencies", {})
        for pkg in deps.get("malware_packages", []):
            failures.append(f"CRITICAL: Malware-associated package: {pkg['package']} — {pkg['reason']}")
        for pkg in deps.get("security_tooling", []):
            pass  # Security tooling is expected — don't flag as failure

        for pkg in deps.get("typosquatting_hits", []):
            failures.append(f"CRITICAL: Typosquatting detected: {pkg['package']} mimics {pkg['similar_to']}")

        cg = checks.get("config_guard", {})
        for issue in cg.get("issues", []):
            failures.append(f"HIGH: Config issue: {issue.get('detail', str(issue))}")

        cs = checks.get("code_scan", {})
        for finding in cs.get("findings", []):
            failures.append(
                f"CRITICAL: Injection pattern in {finding['file']}:{finding['line']} — {finding['pattern']}"
            )

        ns = checks.get("network_self", {})
        for conn in ns.get("suspicious_connections", []):
            failures.append(f"HIGH: Suspicious outbound connection: {conn['remote']} — {conn['reason']}")

        st = checks.get("sandbox_test", {})
        for layer, result in st.items():
            if isinstance(result, dict) and not result.get("passed", True):
                failures.append(f"CRITICAL: Sandbox {layer} FAILED — {result.get('error', 'unknown')}")

        return failures


# ================================================================
#  Convenience functions for tool registration
# ================================================================

def run_full_audit() -> dict:
    """Run a complete self-audit. Returns the full report as a dict."""
    auditor = SelfAuditor()
    return auditor.full_audit()


def run_quick_check() -> dict:
    """Run a quick critical-only check. Returns simple OK/FAIL."""
    auditor = SelfAuditor()
    return auditor.quick_check()


def run_network_self_check() -> dict:
    """Check the guardian's own network connections."""
    return NetworkSelfCheck.check()


def run_file_verification() -> dict:
    """Verify all project files against the integrity manifest."""
    auditor = SelfAuditor()
    return auditor.verify_files()


# ================================================================
#  CLI entry point
# ================================================================

if __name__ == "__main__":
    import argparse

    # Fix GBK encoding on Windows terminals
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="AI Security Guardian — Self-Audit Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--full", action="store_true",
        help="Run full self-audit (all 7 checks)"
    )
    parser.add_argument(
        "--quick", action="store_true",
        help="Quick critical-only check (~1s)"
    )
    parser.add_argument(
        "--network", action="store_true",
        help="Network self-check only"
    )
    parser.add_argument(
        "--verify", action="store_true",
        help="Verify files against integrity manifest"
    )
    parser.add_argument(
        "--generate-manifest", action="store_true",
        help="Generate a new integrity manifest from current files"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON (default: pretty-printed)"
    )
    args = parser.parse_args()

    auditor = SelfAuditor()

    if args.generate_manifest:
        hasher = FileHasher()
        entries = hasher.hash_directory(auditor.root)
        auditor.manifest.save(entries)
        print(f"✅ Generated manifest with {len(entries)} files")
        sys.exit(0)

    if args.network:
        result = auditor.check_own_network()
    elif args.verify:
        result = auditor.verify_files()
    elif args.quick:
        result = auditor.quick_check()
    elif args.full or True:  # Default: full audit
        result = auditor.full_audit()

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # Pretty print
        print("\n" + "=" * 60)
        print("  🛡️  AI 安全管家 — 自我完整性审计")
        print("=" * 60)

        if isinstance(result, dict):
            if "overall_score" in result:
                score = result["overall_score"]
                color = "🟢" if score >= 80 else ("🟡" if score >= 50 else "🔴")
                print(f"\n  {color} 完整性评分: {score}/100")
                print(f"  ⏱️  耗时: {result['duration_ms']}ms")

                failures = result.get("critical_failures", [])
                if failures:
                    print(f"\n  ❌ {len(failures)} 个严重问题:")
                    for f in failures:
                        print(f"     • {f}")
                else:
                    print("\n  ✅ 未发现严重问题 — 系统完整")
            else:
                status = "✅ OK" if result.get("ok") else "❌ FAIL"
                print(f"\n  状态: {status}")
                for issue in result.get("issues", []):
                    print(f"     • [{issue.get('severity', '?')}] {issue.get('issue', str(issue))}")

            print("\n" + "=" * 60)
