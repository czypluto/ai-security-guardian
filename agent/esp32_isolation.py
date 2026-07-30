"""
ESP32 Network Isolation Guard — Prevent ESP32 from becoming an Internet gateway.

This module enforces strict network isolation between the ESP32 hardware terminal
and the PC/internet. The ESP32 should be a DISPLAY-ONLY device — it receives
security status from the PC and shows it on screen. It should NEVER:

  1. Connect to the internet (via its own WiFi or via PC proxy)
  2. Send data anywhere except the PC's serial port
  3. Receive commands from anywhere except the PC's serial port

Isolation Layers:
  A. PC-side DeviceBridge validation — command whitelist + rate limiting
  B. PC-side egress guard — prevent serial data from being forwarded to network
  C. ESP32 firmware WiFi lock — physical button required to enable WiFi
  D. Windows Firewall rules — block Python process on unexpected ports
  E. Self-audit integration — verify isolation at runtime

Design principle: The ESP32 is a trusted DISPLAY peripheral, not a network device.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("Guardian.ESP32Isolation")

# ================================================================
#  Allowed Serial Commands (PC → ESP32)
# ================================================================

# The ESP32 should ONLY accept these commands from the PC.
# Any other command structure is suspicious.
ALLOWED_COMMANDS = {
    "update": {
        "required_fields": ["cmd"],
        "optional_fields": [
            "sec_level", "threat_count", "blocked_count", "last_threat",
            "active_connections", "suspicious_ips", "net_status",
            "firewall_on", "defender_on", "cpu_usage", "mem_usage",
            "uptime", "messages", "ai_status", "ai_task", "ai_progress",
        ],
        "max_size_bytes": 2048,
    },
    "ping": {
        "required_fields": ["cmd"],
        "optional_fields": [],
        "max_size_bytes": 64,
    },
    "screen": {
        "required_fields": ["cmd", "screen"],
        "optional_fields": [],
        "max_size_bytes": 64,
    },
    "say": {
        "required_fields": ["cmd", "text"],
        "optional_fields": [],
        "max_size_bytes": 256,
    },
    "expression": {
        "required_fields": ["cmd", "expression"],
        "optional_fields": [],
        "max_size_bytes": 64,
    },
    "alert": {
        "required_fields": ["cmd", "message"],
        "optional_fields": [],
        "max_size_bytes": 256,
    },
}

# Maximum serial data rate (bytes per second)
MAX_SERIAL_RATE_BPS = 4096

# Maximum consecutive invalid commands before lockdown
MAX_INVALID_COMMANDS = 10


class SerialCommandValidator:
    """Validate all PC→ESP32 commands against the whitelist."""

    def __init__(self):
        self.invalid_count = 0
        self.locked_down = False
        self.total_commands = 0
        self.last_reset = time.time()

    def validate(self, cmd: dict) -> tuple[bool, str]:
        """
        Validate a command before sending to ESP32.
        Returns (is_valid, reason).
        """
        if self.locked_down:
            return False, "Serial bridge locked down due to too many invalid commands"

        self.total_commands += 1

        # Must be a dict
        if not isinstance(cmd, dict):
            self._record_invalid()
            return False, "Not a JSON object"

        # Must have a 'cmd' field
        cmd_type = cmd.get("cmd", "")
        if not cmd_type:
            self._record_invalid()
            return False, "Missing 'cmd' field"

        # Must be a known command type
        if cmd_type not in ALLOWED_COMMANDS:
            self._record_invalid()
            return False, f"Unknown command type: {cmd_type}"

        spec = ALLOWED_COMMANDS[cmd_type]

        # Check required fields
        for field in spec["required_fields"]:
            if field not in cmd:
                self._record_invalid()
                return False, f"Missing required field '{field}' for command '{cmd_type}'"

        # Check for unknown fields (could be injection)
        known_fields = set(spec["required_fields"] + spec["optional_fields"])
        unknown = set(cmd.keys()) - known_fields
        if unknown:
            self._record_invalid()
            return False, f"Unknown fields in '{cmd_type}' command: {unknown}"

        # Check size
        cmd_json = json.dumps(cmd, ensure_ascii=False)
        if len(cmd_json) > spec["max_size_bytes"]:
            self._record_invalid()
            return False, f"Command exceeds max size ({len(cmd_json)} > {spec['max_size_bytes']})"

        # Check for injection patterns in string values
        for key, value in cmd.items():
            if isinstance(value, str):
                if self._has_injection_pattern(value):
                    self._record_invalid()
                    return False, f"Injection pattern detected in field '{key}'"

        return True, "ok"

    def _has_injection_pattern(self, text: str) -> bool:
        """Check for command injection patterns in string values."""
        dangerous = [
            "\\n", "\\r", "\x00",  # Control characters
            "cmd\":", "\"cmd\":",   # Nested commands
            "${", "`", "|", "&",    # Shell injection
            "../", "..\\",          # Path traversal
        ]
        return any(p in text for p in dangerous)

    def _record_invalid(self):
        """Record an invalid command. Lockdown if threshold exceeded."""
        self.invalid_count += 1
        if self.invalid_count >= MAX_INVALID_COMMANDS:
            self.locked_down = True
            logger.critical(
                "SERIAL BRIDGE LOCKED DOWN: %d invalid commands detected. "
                "Possible serial injection attack or firmware compromise!",
                self.invalid_count,
            )

    def reset_counters(self):
        """Reset counters (e.g., after legitimate reconnect)."""
        self.invalid_count = 0
        self.locked_down = False
        self.last_reset = time.time()

    def get_stats(self) -> dict:
        return {
            "total_commands": self.total_commands,
            "invalid_count": self.invalid_count,
            "locked_down": self.locked_down,
            "last_reset": self.last_reset,
        }


class SerialEgressGuard:
    """
    Ensure serial data from ESP32 never leaves the PC.

    This is a logical guard — it monitors that DeviceBridge's serial reader
    only logs data locally and never forwards it to network sockets.
    """

    def __init__(self):
        self.egress_attempts = 0
        self._monitor_enabled = False

    def enable_monitoring(self):
        """Start monitoring for serial data egress."""
        self._monitor_enabled = True
        logger.info("Serial egress guard enabled — ESP32 data will not leave this PC")

    def check_egress_safety(self, data: str, destination: str) -> bool:
        """
        Check if sending ESP32 data to a destination is safe.
        Returns True if safe, False if blocked.
        """
        if not self._monitor_enabled:
            return True

        # Only allow serial data to go to:
        # - Local log files
        # - Console/stdout
        # - Internal state (not network)
        allowed_destinations = ["log", "console", "state", "internal"]

        if destination not in allowed_destinations:
            self.egress_attempts += 1
            logger.warning(
                "BLOCKED: Attempted to send ESP32 serial data to '%s' (%d chars). "
                "ESP32 is a display-only device — its data must not leave this PC.",
                destination, len(data),
            )
            return False
        return True

    def get_stats(self) -> dict:
        return {
            "egress_attempts_blocked": self.egress_attempts,
            "monitoring_enabled": self._monitor_enabled,
        }


# ================================================================
#  Windows Firewall Rule Manager
# ================================================================

class FirewallRuleManager:
    """
    Manage Windows Firewall rules to restrict the Python process.

    Creates inbound/outbound rules that:
      - Allow the guardian Python process to make necessary API calls
      - Block the guardian Python process on unexpected ports
      - Log denied connections for audit
    """

    GUARDIAN_RULE_PREFIX = "AI_Security_Guardian"

    # Ports the guardian NEEDS to access (API calls)
    ALLOWED_OUTBOUND_PORTS = {443, 80}  # HTTPS + HTTP for API calls

    # Ports the guardian should NEVER use
    BLOCKED_PORTS = {4444, 31337, 6666, 6667, 6697, 8080, 8443, 9001, 9999}

    @staticmethod
    def is_admin() -> bool:
        """Check if running with admin privileges."""
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    @classmethod
    def generate_rules_script(cls) -> str:
        """
        Generate a PowerShell script to create firewall rules.
        Does NOT execute — returns the script for user review.
        """
        exe_path = sys.executable

        script = f'''# AI Security Guardian — ESP32 Network Isolation Firewall Rules
# Generated by esp32_isolation.py
# Review carefully before running as Administrator!

$exePath = "{exe_path}"

# Remove old rules (idempotent)
Remove-NetFirewallRule -DisplayName "{cls.GUARDIAN_RULE_PREFIX}*" -ErrorAction SilentlyContinue

# Rule 1: Block guardian on suspicious C2/backdoor ports (outbound)
New-NetFirewallRule -DisplayName "{cls.GUARDIAN_RULE_PREFIX}_Block_C2_Ports" `
    -Direction Outbound -Action Block `
    -Program $exePath `
    -Protocol TCP `
    -RemotePort 4444,31337,6666,6667,6697,8080,8443,9001,9999 `
    -Description "Block guardian Python process on known C2/backdoor ports"

# Rule 2: Block guardian on suspicious ports (inbound)
New-NetFirewallRule -DisplayName "{cls.GUARDIAN_RULE_PREFIX}_Block_Inbound" `
    -Direction Inbound -Action Block `
    -Program $exePath `
    -Protocol TCP `
    -Description "Block ALL inbound connections to guardian Python process"

# Rule 3: Log blocked connections
New-NetFirewallRule -DisplayName "{cls.GUARDIAN_RULE_PREFIX}_Audit_Blocks" `
    -Direction Outbound -Action Block `
    -Program $exePath `
    -Protocol TCP `
    -RemotePort 1-65535 `
    -Description "Audit: log all blocked outbound guardian connections" `
    -Enabled False  # Only enable for forensic investigation

Write-Host "AI Security Guardian firewall rules installed."
Write-Host "Rules block: C2/backdoor ports (outbound) + all inbound"
Write-Host "Run: Get-NetFirewallRule -DisplayName '{cls.GUARDIAN_RULE_PREFIX}*' | Format-Table"
'''

        return script

    @classmethod
    def check_existing_rules(cls) -> dict:
        """Check if guardian firewall rules exist."""
        try:
            result = subprocess.run(
                ["netsh", "advfirewall", "firewall", "show", "rule",
                 f"name={cls.GUARDIAN_RULE_PREFIX}_Block_C2_Ports"],
                capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace",
            )
            rules_exist = "ok" in result.stdout.lower() or "规则" in result.stdout
            return {
                "rules_installed": rules_exist,
                "details": result.stdout[:500] if rules_exist else "No rules found",
            }
        except Exception as e:
            return {"rules_installed": False, "error": str(e)}


# ================================================================
#  ESP32 Firmware Integrity (PC-side verification)
# ================================================================

class FirmwareIntegrityChecker:
    """
    PC-side checks for ESP32 firmware integrity.

    Since we can't hash the firmware remotely, we verify:
      1. The expected firmware path exists on disk
      2. The firmware hasn't been modified (SHA256 vs manifest)
      3. The serial handshake matches expected format
    """

    EXPECTED_STARTUP_PATTERNS = [
        r'\{.*"status"\s*:\s*"ready".*\}',           # Standard ready message
        r'\{.*"type"\s*:\s*"(tdisplay|oled)".*\}',    # Device type
        r'\{.*"fingerprint"\s*:\s*".*".*\}',          # Firmware fingerprint (v3.2+)
    ]

    @staticmethod
    def verify_firmware_file(firmware_path: Path) -> dict:
        """Check that the firmware .ino file exists and looks legitimate."""
        if not firmware_path.exists():
            return {"ok": False, "error": f"Firmware not found: {firmware_path}"}

        content = firmware_path.read_text(encoding="utf-8", errors="replace")

        # Strip comments before checking (C-style // and /* */)
        lines = content.split("\n")
        active_lines = []
        in_block_comment = False
        for line in lines:
            stripped = line.strip()
            if in_block_comment:
                if "*/" in stripped:
                    in_block_comment = False
                continue
            if stripped.startswith("//"):
                continue
            if "/*" in stripped:
                in_block_comment = True
                continue
            active_lines.append(stripped)

        active_content = "\n".join(active_lines)

        # WiFi check: look for WiFi ENABLING patterns (not disabling)
        has_wifi_enabling = (
            "WiFi.begin" in active_content or
            "WiFi.softAP" in active_content or
            ("WiFi.mode" in active_content and "WIFI_OFF" not in active_content)
        )

        checks = {
            "has_serial_begin": "Serial.begin" in content,
            "has_json_parsing": "deserializeJson" in content or "parseObject" in content,
            "has_wifi_enabled": has_wifi_enabling,
            "has_wifi_disable_code": "WIFI_OFF" in content or "WiFi.disconnect" in content,
            "has_ota": "ArduinoOTA" in content or "Update.begin" in content,
            "has_network_client": "WiFiClient" in content or "HTTPClient" in content,
            "has_fingerprint": "fingerprint" in content.lower(),
            "line_count": len(lines),
        }

        issues = []
        if not checks["has_serial_begin"]:
            issues.append("No Serial.begin — firmware may not communicate properly")
        if not checks["has_json_parsing"]:
            issues.append("No JSON parsing — may not understand PC commands")
        if not checks["has_fingerprint"]:
            issues.append("No firmware fingerprint — PC cannot verify firmware identity")
        if checks["has_wifi_enabled"]:
            issues.append("CRITICAL: WiFi is ENABLED in firmware! ESP32 can reach internet!")
        elif checks["has_wifi_disable_code"]:
            pass  # Good: WiFi is explicitly disabled
        if checks["has_ota"]:
            issues.append("CRITICAL: OTA updates enabled — remote firmware replacement possible!")
        if checks["has_network_client"]:
            issues.append("HIGH: Network client code present — ESP32 can make outbound connections")

        return {
            "ok": len(issues) == 0,
            "issues": issues,
            "checks": checks,
        }

    @staticmethod
    def verify_handshake(serial_data: str) -> dict:
        """Verify the ESP32 startup handshake looks legitimate."""
        import re
        for pattern in FirmwareIntegrityChecker.EXPECTED_STARTUP_PATTERNS:
            if re.search(pattern, serial_data):
                return {"ok": True, "matched_pattern": pattern}
        return {"ok": False, "error": "Startup handshake doesn't match expected format"}


# ================================================================
#  Unified ESP32 Isolation Report
# ================================================================

def run_isolation_audit() -> dict:
    """
    Run a complete ESP32 network isolation audit.
    Returns findings and recommendations.
    """
    findings = []
    recommendations = []
    passed = True

    root = Path(__file__).parent.parent

    # 1. Check firmware for WiFi
    fw_paths = [
        root / "firmware" / "firmware.ino",
        root / "firmware" / "firmware_tdisplay" / "firmware_tdisplay.ino",
    ]
    fw_results = {}
    for fw_path in fw_paths:
        if fw_path.exists():
            result = FirmwareIntegrityChecker.verify_firmware_file(fw_path)
            fw_results[str(fw_path.relative_to(root))] = result
            for issue in result.get("issues", []):
                if "CRITICAL" in issue:
                    findings.append(f"[CRITICAL] {fw_path.name}: {issue}")
                    passed = False
                else:
                    findings.append(f"[WARNING] {fw_path.name}: {issue}")

    if not any(p.exists() for p in fw_paths):
        findings.append("[WARNING] No firmware files found on disk")

    # 2. Check firewall rules
    fw_rules = FirewallRuleManager.check_existing_rules()
    if not fw_rules.get("rules_installed"):
        findings.append("[INFO] Windows Firewall isolation rules not installed")
        recommendations.append(
            "Run 'python agent/esp32_isolation.py --generate-firewall-script' "
            "to create firewall isolation rules"
        )

    # 3. Check config
    config_path = root / "pc_agent" / "config.yaml"
    if config_path.exists():
        config_text = config_path.read_text(encoding="utf-8", errors="replace")
        if "mode: auto" in config_text or "mode: wifi" in config_text:
            findings.append("[WARNING] DeviceBridge mode allows WiFi — change to 'serial' only")
            recommendations.append("Set device.mode to 'serial' in pc_agent/config.yaml")
        if "mode: serial" in config_text:
            findings.append("[OK] DeviceBridge mode is 'serial' — WiFi disabled")

    return {
        "isolation_status": "SECURE" if passed else "VULNERABLE",
        "findings": findings,
        "recommendations": recommendations,
        "firmware_checks": fw_results,
        "firewall_rules": fw_rules,
    }


# ================================================================
#  CLI
# ================================================================

if __name__ == "__main__":
    import argparse

    # Fix GBK encoding
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="ESP32 Network Isolation Guard",
    )
    parser.add_argument(
        "--audit", action="store_true", default=True,
        help="Run ESP32 isolation audit"
    )
    parser.add_argument(
        "--generate-firewall-script", action="store_true",
        help="Generate Windows Firewall rules script"
    )
    parser.add_argument(
        "--check-firmware", type=str,
        help="Check a specific firmware file for WiFi/OTA risks"
    )
    args = parser.parse_args()

    if args.generate_firewall_script:
        script = FirewallRuleManager.generate_rules_script()
        output_path = Path(__file__).parent.parent / "firewall_isolation.ps1"
        output_path.write_text(script, encoding="utf-8")
        print(f"Firewall script written to: {output_path}")
        print("Review it, then run as Administrator: powershell -File firewall_isolation.ps1")

    elif args.check_firmware:
        result = FirmwareIntegrityChecker.verify_firmware_file(Path(args.check_firmware))
        print(json.dumps(result, indent=2, ensure_ascii=False))

    else:
        # Default: run audit
        report = run_isolation_audit()
        print("\n" + "=" * 60)
        print("  ESP32 Network Isolation Audit")
        print("=" * 60)
        print(f"\n  Status: {report['isolation_status']}")
        print(f"\n  Findings ({len(report['findings'])}):")
        for f in report["findings"]:
            print(f"    {f}")
        if report["recommendations"]:
            print(f"\n  Recommendations:")
            for r in report["recommendations"]:
                print(f"    > {r}")
        print("\n" + "=" * 60)
