#!/usr/bin/env python3
"""
Claude Code PreToolUse Hook — Auto-scan all downloaded/installed content.

Intercepts:
  - Write tool → .md files in skills/ (skill installation)
  - Write tool → .py/.yaml/.json files in agent/ or pc_agent/ (code injection)
  - Bash tool  → npm install, npx, pip install, git clone (external content)
  - Bash tool  → curl/wget with pipe to shell (command injection)

Returns JSON with "decision": "block" to prevent the operation, or "allow" to proceed.

Usage in .claude/settings.json:
  {
    "hooks": {
      "PreToolUse": [
        {
          "matcher": "Write",
          "hooks": [{
            "type": "command",
            "command": "python .claude/hooks/pre_download_scan.py write"
          }]
        },
        {
          "matcher": "Bash",
          "hooks": [{
            "type": "command",
            "command": "python .claude/hooks/pre_download_scan.py bash"
          }]
        }
      ]
    }
  }
"""
import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def log(msg: str):
    """Log to stderr (stdout is parsed by Claude Code)."""
    print(f"[PreDownloadScan] {msg}", file=sys.stderr)


def main():
    # Read the hook input from stdin (Claude Code passes tool call data as JSON)
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        # No input or invalid — allow by default (fail-open for usability)
        print(json.dumps({"decision": "allow"}))
        return 0

    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})

    if tool_name == "Write":
        result = check_write(tool_input)
    elif tool_name == "Bash":
        result = check_bash(tool_input)
    else:
        result = {"decision": "allow"}

    print(json.dumps(result))
    return 0


def check_write(tool_input: dict) -> dict:
    """Check Write tool calls for skill/plugin/code installation."""
    file_path = tool_input.get("file_path", "")
    content = tool_input.get("content", "")

    if not file_path:
        return {"decision": "allow"}

    path_lower = file_path.lower()
    path_obj = Path(file_path)

    # === Check: Writing .md files to skills/ ===
    if path_lower.endswith(".md") and "skills" in path_obj.parts:
        return scan_content(content, "skill", file_path)

    # === Check: Writing .py files to agent/ or pc_agent/ ===
    if path_lower.endswith(".py"):
        if any(p in path_obj.parts for p in ("agent", "pc_agent")):
            return scan_content(content, "script", file_path)

    # === Check: Writing .yaml/.json config files ===
    if path_lower.endswith((".yaml", ".yml", ".json")):
        if "mcp" in path_lower or "config" in path_lower:
            return scan_content(content, "mcp_config", file_path)

    # === Check: Writing .bat/.ps1/.sh scripts ===
    if path_lower.endswith((".bat", ".ps1", ".sh")):
        return scan_content(content, "script", file_path)

    return {"decision": "allow"}


def check_bash(tool_input: dict) -> dict:
    """Check Bash tool calls for install/download commands."""
    command = tool_input.get("command", "")

    if not command:
        return {"decision": "allow"}

    cmd_lower = command.lower()

    # === Patterns that trigger scanning ===
    install_patterns = [
        "npm install", "npm i ", "npx ", "yarn add", "pnpm add",
        "pip install", "pip3 install", "python -m pip install",
        "git clone", "git pull",
        "curl ", "wget ",
        "python -m ensurepip",
        "gem install", "cargo install",
    ]

    should_scan = any(pattern in cmd_lower for pattern in install_patterns)

    if not should_scan:
        return {"decision": "allow"}

    # === Special: curl/wget piped to shell ===
    pipe_to_shell = [
        "curl", "| bash", "| sh", "| cmd",
        "| powershell", "| pwsh",
        "wget", "-o- |", "-O- |",
    ]

    for pattern in pipe_to_shell:
        if pattern in cmd_lower:
            log(f"BLOCKED: Pipe-to-shell detected: {command[:120]}")
            return {
                "decision": "block",
                "reason": (
                    "Pipe-to-shell is the #1 attack vector for malware. "
                    "Download the script first, review it, then run it separately."
                ),
                "suggestion": (
                    f"1. Download: {command.split('|')[0].strip()} -o install.sh\n"
                    f"2. Review:  cat install.sh\n"
                    f"3. Run:    bash install.sh"
                ),
            }

    # === Check for suspicious flags in install commands ===
    dangerous_flags = [
        "--allow-dangerous", "--no-sandbox", "--unsafe-perm",
        "--disable-security", "--insecure",
    ]
    for flag in dangerous_flags:
        if flag in cmd_lower:
            log(f"BLOCKED: Dangerous flag '{flag}' in: {command[:120]}")
            return {
                "decision": "block",
                "reason": f"Dangerous flag detected: '{flag}'. This disables security protections.",
            }

    # === Scan the command itself ===
    return scan_content(command, "mcp_config", f"bash: {command[:80]}")


def scan_content(content: str, file_type: str, source: str) -> dict:
    """Run the download scanner on content. Returns hook decision."""
    if not content:
        return {"decision": "allow"}

    try:
        from agent.download_scanner import scan_before_install

        result = scan_before_install(content, file_type=file_type, source=source)

        if not result.safe:
            findings_summary = [
                f"[{f['severity']}] {f['category']}: {f['detail'][:100]}"
                for f in result.findings
                if f["severity"] in ("CRITICAL", "HIGH")
            ]

            log(f"BLOCKED: {source} — score {result.score}/100 — {len(findings_summary)} issues")
            for fs in findings_summary[:5]:
                log(f"  {fs}")

            return {
                "decision": "block",
                "reason": (
                    f"Security scan rejected this content (score: {result.score}/100). "
                    f"Found {len(findings_summary)} critical/high severity issues."
                ),
                "findings": findings_summary[:5],
                "suggestion": (
                    "If you trust this source, review the content manually. "
                    "To bypass: remove suspicious patterns and try again."
                ),
            }

        log(f"ALLOWED: {source} — score {result.score}/100 — clean")
        return {"decision": "allow"}

    except ImportError as e:
        log(f"Scanner unavailable: {e} — allowing by default")
        return {"decision": "allow"}
    except Exception as e:
        log(f"Scan error: {e} — allowing by default (fail-open for usability)")
        return {"decision": "allow"}


if __name__ == "__main__":
    sys.exit(main())
