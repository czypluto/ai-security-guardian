"""
Download Pre-Scan Module — Security check for all externally downloaded content.

Scans skills, plugins, MCP configs, and any downloaded file BEFORE installation.
Detects: prompt injection, hidden text, obfuscation, suspicious URLs, typosquatting,
and code execution patterns.

Usage:
    from agent.download_scanner import scan_before_install

    result = scan_before_install(content, file_type="skill")
    if result["safe"]:
        install(skill)
    else:
        reject(result["findings"])
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("Guardian.DownloadScanner")

# ================================================================
#  Detection Patterns
# ================================================================

# Prompt injection — attempts to hijack the AI agent
PROMPT_INJECTION_PATTERNS = [
    # Direct override
    r"(?i)(ignore|forget|disregard)\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?|context)",
    r"(?i)(you\s+are\s+now|you\s+must\s+now|from\s+now\s+on\s+you)",
    r"(?i)(your\s+new\s+(system\s+)?prompt|your\s+new\s+instructions?)",
    r"(?i)(override|replace)\s+(the\s+)?(system\s+)?(prompt|instructions?)",
    r"(?i)(act\s+as\s+if|pretend\s+(you\s+are|to\s+be)|roleplay\s+as)",
    # Jailbreak tricks
    r"(?i)(DAN\s|jailbreak|bypass\s+(the\s+)?(filter|guardrail|safety))",
    r"(?i)(pretend\s+to\s+be\s+a|act\s+like\s+a\s+malicious)",
    # Hidden instructions
    r"(?i)(?<!\w)(system|assistant|user|human)\s*:\s*[Nn]ever\s",
    r"(?i)(IMPORTANT|CRITICAL)\s*:\s*(ignore|override|bypass)",
    # Social engineering
    r"(?i)(this\s+is\s+(urgent|critical|mandatory|required))",
    r"(?i)(you\s+have\s+no\s+choice|you\s+MUST|failure\s+(is\s+not|isn't)\s+an\s+option)",
]

# Code execution patterns in text files (should never be in .md skills)
CODE_EXECUTION_PATTERNS = [
    r"(?i)os\.system\s*\(",
    r"(?i)subprocess\.(call|run|Popen)\s*\(",
    r"(?i)eval\s*\(|exec\s*\(|compile\s*\(",
    r"(?i)__import__\s*\(",
    r"(?i)ctypes\.(windll|cdll|pythonapi)",
    r"(?i)(rm\s+-rf\s+/|del\s+/[fsq]\s+)",  # Destructive commands
    r"(?i)(curl|wget)\s+.*\|\s*(bash|sh|cmd|powershell)",
    r"(?i)nc\s+-[el]\s+\d+",  # Netcat reverse shell
    r"(?i)bash\s+-[ci]\s+.*>&\s*/dev/tcp/",  # Bash reverse shell
    r"(?i)powershell\s+.*-enc\s+[A-Za-z0-9+/=]{50,}",  # Base64-encoded PowerShell
    r"(?i)Invoke-(Expression|Command|WebRequest)\s",
    r"(?i)Start-Process\s+.*-WindowStyle\s+Hidden",
    r"(?i)iex\s*\(|iwr\s+.*\|.*iex",
]

# Obfuscation patterns
OBFUSCATION_PATTERNS = [
    r"data\s*:\s*text/html\s*;base64",  # HTML smuggling in text
    r"&#x?[0-9a-fA-F]+;",               # HTML entity encoding
    r"\\x[0-9a-fA-F]{2}\\x[0-9a-fA-F]{2}",  # Hex-encoded bytes
    r"\\u[0-9a-fA-F]{4}\\u[0-9a-fA-F]{4}",  # Unicode escapes
    r"String\.fromCharCode\s*\(",          # JS obfuscation
    r"atob\s*\(|btoa\s*\(.*,",            # Base64 in JS
    r"\[char\]\d+",                        # PowerShell char cast
]

# Suspicious URLs (malware C2, phishing, exfiltration endpoints)
SUSPICIOUS_URL_PATTERNS = [
    r"(?i)\.onion(/|$|\s)",
    r"(?i)\.tk(/|$|\s)",  # Free domain, common for malware
    r"(?i)\.ml(/|$|\s)",
    r"(?i)\.ga(/|$|\s)",
    r"(?i)\.cf(/|$|\s)",
    r"(?i)(pastebin\.com|pastie\.org|justpaste\.it)",
    r"(?i)(ngrok|localhost\.run|serveo\.net)",
    r"(?i)(discord\.com/api/webhooks)",  # Data exfiltration vector
    r"(?i)(telegram\.org/bot)",          # Bot-based exfiltration
    r"(?i)requestbin\.(com|net|org)",
    r"(?i)webhook\.site",
]

# Hidden Unicode characters (invisible text injection)
INVISIBLE_CHARACTERS = [
    '​',  # Zero-width space
    '‌',  # Zero-width non-joiner
    '‍',  # Zero-width joiner
    '‎',  # Left-to-right mark
    '‏',  # Right-to-left mark
    '‪',  # Left-to-right embedding
    '‫',  # Right-to-left embedding
    '‬',  # Pop directional formatting
    '‭',  # Left-to-right override
    '‮',  # Right-to-left override
    '⁠',  # Word joiner
    '⁡',  # Function application
    '⁢',  # Invisible times
    '⁣',  # Invisible separator
    '⁤',  # Invisible plus
    '﻿',  # BOM / Zero-width no-break space
    '­',  # Soft hyphen
    '͏',  # Combining grapheme joiner
    '؜',  # Arabic letter mark
    '᠎',  # Mongolian vowel separator
]

# ================================================================
#  Scanner
# ================================================================

class ScanResult:
    """Result of a security scan."""

    def __init__(self):
        self.findings: list[dict] = []
        self.safe = True
        self.score = 100  # 100 = clean, 0 = definitely malicious

    def add(self, severity: str, category: str, detail: str, location: str = ""):
        finding = {
            "severity": severity,  # CRITICAL, HIGH, MEDIUM, LOW, INFO
            "category": category,
            "detail": detail,
            "location": location,
        }
        self.findings.append(finding)

        # Adjust score
        penalties = {"CRITICAL": 50, "HIGH": 20, "MEDIUM": 10, "LOW": 5, "INFO": 0}
        self.score = max(0, self.score - penalties.get(severity, 10))

        if severity in ("CRITICAL", "HIGH"):
            self.safe = False


def scan_before_install(
    content: str,
    file_type: str = "unknown",
    source: str = "",
    max_size_bytes: int = 1024 * 1024,  # 1MB default max
) -> ScanResult:
    """
    Scan downloaded content BEFORE installation.

    Args:
        content: The file content (string for text, or path for binary)
        file_type: "skill", "mcp_config", "script", "binary", "unknown"
        source: Where the file came from (URL, filename, etc.)
        max_size_bytes: Maximum allowed file size

    Returns:
        ScanResult with findings, safe flag, and score
    """
    result = ScanResult()

    # 0. Size check
    content_size = len(content.encode("utf-8")) if isinstance(content, str) else 0
    if content_size > max_size_bytes:
        result.add("CRITICAL", "size", f"File too large: {content_size} bytes (max {max_size_bytes})")
        return result
    if content_size > 100 * 1024 and file_type == "skill":
        result.add("MEDIUM", "size", f"Skill file unusually large: {content_size} bytes. Skills should be <50KB")

    # 1. Hidden Unicode characters (check first — invisible text is always malicious)
    hidden_chars_found = []
    for i, char in enumerate(content):
        if char in INVISIBLE_CHARACTERS:
            hidden_chars_found.append({
                "char": f"U+{ord(char):04X}",
                "name": unicodedata.name(char, "UNKNOWN"),
                "position": i,
            })
    if hidden_chars_found:
        result.add("CRITICAL", "hidden_text",
                   f"Found {len(hidden_chars_found)} invisible Unicode characters. "
                   f"This is a common technique to hide malicious instructions.",
                   str(hidden_chars_found[:10]))
    if hidden_chars_found and file_type == "skill":
        result.add("CRITICAL", "hidden_text",
                   "Hidden text in skill file — likely prompt injection attack. REJECTED.")

    # 2. Prompt injection patterns (for skills, prompts, configs)
    if file_type in ("skill", "mcp_config", "unknown"):
        for pattern in PROMPT_INJECTION_PATTERNS:
            matches = re.findall(pattern, content, re.IGNORECASE | re.MULTILINE)
            if matches:
                result.add("HIGH", "prompt_injection",
                           f"Prompt injection pattern detected: '{pattern}'",
                           str(matches[:3]))
                break  # One injection finding is enough

    # 3. Code execution patterns (for text files)
    if file_type in ("skill", "script", "mcp_config", "unknown"):
        for pattern in CODE_EXECUTION_PATTERNS:
            matches = re.findall(pattern, content, re.IGNORECASE | re.MULTILINE)
            for match in matches[:3]:
                result.add("CRITICAL" if file_type == "skill" else "HIGH",
                           "code_execution",
                           f"Code execution pattern in {file_type}: '{match}'")

    # 4. Obfuscation detection
    obfuscation_count = 0
    for pattern in OBFUSCATION_PATTERNS:
        matches = re.findall(pattern, content, re.IGNORECASE | re.MULTILINE)
        obfuscation_count += len(matches)
    if obfuscation_count > 3:
        result.add("HIGH", "obfuscation",
                   f"Multiple obfuscation indicators ({obfuscation_count}) — "
                   f"this content may be deliberately hidden")

    # 5. Suspicious URLs
    urls_found = re.findall(r'https?://[^\s<>"\')\]]+', content)
    for url in urls_found:
        for pattern in SUSPICIOUS_URL_PATTERNS:
            if re.search(pattern, url):
                result.add("MEDIUM", "suspicious_url",
                           f"Suspicious URL in {file_type}: {url} (matched: {pattern})")

    # 6. Content type-specific checks
    if file_type == "skill":
        _scan_skill_specific(content, result)
    elif file_type == "mcp_config":
        _scan_mcp_specific(content, result)
    elif file_type == "script":
        _scan_script_specific(content, result)

    # 7. Metadata
    if source:
        result.add("INFO", "metadata", f"Scanned content from: {source}")

    return result


def _scan_skill_specific(content: str, result: ScanResult):
    """Checks specific to .md skill files."""
    # Skills should have YAML frontmatter
    has_frontmatter = content.strip().startswith("---")
    if not has_frontmatter:
        result.add("MEDIUM", "skill_format", "No YAML frontmatter — skill may be malformed")

    # Skills should be mostly natural language, not code
    code_lines = 0
    total_lines = 0
    for line in content.split("\n"):
        total_lines += 1
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("//"):
            if any(kw in stripped for kw in [
                "def ", "class ", "import ", "from ", "async def",
                "function", "const ", "let ", "var ",
                "#!/", "set -e", "export ",
            ]):
                code_lines += 1

    if total_lines > 0 and code_lines / total_lines > 0.3:
        result.add("HIGH", "skill_code_ratio",
                   f"Skill is {code_lines}/{total_lines} code lines (>30%). "
                   f"Skills should be natural language instructions, not executable code.")

    # Check for excessively long lines (potential base64 or encoded payload)
    long_lines = [l for l in content.split("\n") if len(l) > 500]
    if long_lines:
        result.add("MEDIUM", "skill_long_lines",
                   f"{len(long_lines)} lines exceed 500 chars — possible encoded payload")

    # Check for attempts to access filesystem or network from skill
    fs_patterns = [
        (r"(?i)(write\s+(to\s+)?file|save\s+(to|as)\s+|create\s+file)", "file write attempt in skill"),
        (r"(?i)(read\s+(from\s+)?file|open\s+file|load\s+file)", "file read attempt in skill"),
        (r"(?i)(delete\s+file|remove\s+file|wipe\s+file)", "file deletion attempt in skill"),
        (r"(?i)(send\s+(a\s+)?request|fetch\s+url|http\.get|http\.post)", "network request from skill"),
    ]
    for pattern, description in fs_patterns:
        if re.search(pattern, content):
            result.add("HIGH", "skill_fs_access", description)


def _scan_mcp_specific(content: str, result: ScanResult):
    """Checks specific to MCP server configs/recommendations."""
    # Check for dangerous npm/uvx flags
    dangerous_flags = [
        r"--allow-dangerous", r"--no-sandbox", r"--unsafe-perm",
        r"--disable-security", r"--insecure",
    ]
    for flag in dangerous_flags:
        if flag in content.lower():
            result.add("CRITICAL", "mcp_dangerous_flag",
                       f"MCP command uses dangerous flag: '{flag}'")

    # Check for suspicious npm packages
    npm_match = re.search(r'npx\s+(@?[\w\-/]+)', content)
    if npm_match:
        pkg_name = npm_match.group(1)
        typosquatting_check = check_typosquatting(pkg_name)
        if typosquatting_check:
            result.add("HIGH", "mcp_typosquatting", typosquatting_check)

    # Check for pip packages
    pip_match = re.search(r'pip\s+install\s+([\w\-]+)', content)
    if pip_match:
        pkg_name = pip_match.group(1)
        typosquatting_check = check_typosquatting(pkg_name)
        if typosquatting_check:
            result.add("HIGH", "mcp_typosquatting", typosquatting_check)


def _scan_script_specific(content: str, result: ScanResult):
    """Checks specific to script files (.bat, .ps1, .sh, .py)."""
    # Scripts should be treated as high-risk
    result.add("INFO", "script_warning",
               "Script files can execute arbitrary code — manual review required")

    # Check for common malicious patterns
    patterns = [
        (r"(?i)Set-MpPreference.*-Disable", "Disabling Windows Defender"),
        (r"(?i)Add-MpPreference.*-ExclusionPath", "Adding Defender exclusions"),
        (r"(?i)(firewall|netsh).*(disable|allow|add rule)", "Firewall modification"),
        (r"(?i)schtasks\s+/create", "Creating scheduled task (persistence)"),
        (r"(?i)(reg\s+add|New-ItemProperty).*\\Run", "Registry Run key (persistence)"),
        (r"(?i)sc\s+create.*start=\s*auto", "Creating auto-start service (persistence)"),
    ]
    for pattern, description in patterns:
        if re.search(pattern, content):
            result.add("CRITICAL", "script_malicious", description)


# ================================================================
#  Utility: Typosquatting Detection
# ================================================================

# Common legitimate packages (for typo comparison)
COMMON_PACKAGES = [
    "@anthropic/mcp", "@anthropic/mcp-server-filesystem",
    "@modelcontextprotocol/server-filesystem",
    "@modelcontextprotocol/server-github",
    "@modelcontextprotocol/server-postgres",
    "@modelcontextprotocol/server-puppeteer",
    "@modelcontextprotocol/server-brave-search",
    "@modelcontextprotocol/server-fetch",
    "chromadb", "sentence-transformers", "psutil", "pyqt5",
    "pyserial", "pyyaml", "requests", "flask", "numpy",
    "pandas", "pytest", "fastapi", "uvicorn",
]


def check_typosquatting(package_name: str) -> Optional[str]:
    """Check if a package name may be typosquatting a known good package."""
    name_lower = package_name.lower().strip("@").split("/")[-1]

    for known in COMMON_PACKAGES:
        known_lower = known.lower().strip("@").split("/")[-1]
        if name_lower == known_lower:
            return None  # Exact match, not typosquatting

        # Levenshtein distance <= 2 and similar length
        if abs(len(name_lower) - len(known_lower)) <= 2:
            dist = _levenshtein(name_lower, known_lower)
            if 0 < dist <= 2:
                return (f"Package '{package_name}' closely resembles '{known}' "
                        f"(edit distance: {dist}). Possible typosquatting attack!")

    return None


def _levenshtein(s1: str, s2: str) -> int:
    """Compute Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            curr_row.append(min(
                prev_row[j + 1] + 1,      # Insert
                curr_row[j] + 1,          # Delete
                prev_row[j] + (c1 != c2), # Substitute
            ))
        prev_row = curr_row
    return prev_row[-1]


# ================================================================
#  Quick Scan (for use in installers)
# ================================================================

def quick_scan_skill(name: str, content: str, source: str = "") -> dict:
    """
    Quick scan for skill installation. Returns a simple pass/fail dict.
    Designed to be called by installer.py before writing a skill to disk.
    """
    result = scan_before_install(content, file_type="skill", source=source)

    return {
        "passed": result.safe,
        "score": result.score,
        "findings": [
            {"severity": f["severity"], "detail": f["detail"]}
            for f in result.findings
            if f["severity"] in ("CRITICAL", "HIGH")
        ],
        "warning_count": len([f for f in result.findings
                              if f["severity"] in ("CRITICAL", "HIGH")]),
    }


def quick_scan_mcp(name: str, install_command: str, description: str = "") -> dict:
    """
    Quick scan for MCP server recommendation.
    Checks the install command for dangerous patterns.
    """
    combined = f"Command: {install_command}\nDescription: {description}"
    result = scan_before_install(combined, file_type="mcp_config", source=name)

    return {
        "passed": result.safe,
        "score": result.score,
        "findings": [
            {"severity": f["severity"], "detail": f["detail"]}
            for f in result.findings
            if f["severity"] in ("CRITICAL", "HIGH")
        ],
        "warning_count": len([f for f in result.findings
                              if f["severity"] in ("CRITICAL", "HIGH")]),
    }


# ================================================================
#  File-level scan
# ================================================================

def scan_file(file_path: str) -> ScanResult:
    """
    Scan a file on disk before allowing execution/installation.
    """
    path = Path(file_path)
    if not path.exists():
        result = ScanResult()
        result.add("CRITICAL", "file", f"File not found: {file_path}")
        return result

    # Detect file type
    suffix = path.suffix.lower()
    type_map = {
        ".md": "skill",
        ".yaml": "mcp_config",
        ".yml": "mcp_config",
        ".json": "mcp_config",
        ".py": "script",
        ".bat": "script",
        ".ps1": "script",
        ".sh": "script",
        ".js": "script",
    }
    file_type = type_map.get(suffix, "unknown")

    # Read and scan
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        result = ScanResult()
        result.add("CRITICAL", "file", f"Cannot read file: {e}")
        return result

    result = scan_before_install(content, file_type=file_type, source=str(path))

    # Additional binary checks
    if path.stat().st_size > 10 * 1024 * 1024:
        result.add("MEDIUM", "size", f"Large file: {path.stat().st_size} bytes")

    return result


# ================================================================
#  Tool Handlers (for tool registry)
# ================================================================

def scan_download_handler(content: str, file_type: str = "unknown",
                          source: str = "") -> dict:
    """
    Scan downloaded content before installation.
    Tool handler for scan_download tool.
    """
    result = scan_before_install(content, file_type=file_type, source=source)

    return {
        "safe": result.safe,
        "score": result.score,
        "findings": result.findings,
        "recommendation": (
            "SAFE to install" if result.safe
            else "REJECT — contains suspicious content"
        ),
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "content_length": len(content),
    }


def scan_file_handler(file_path: str) -> dict:
    """
    Scan an existing file for security issues.
    Tool handler for scan_file tool.
    """
    result = scan_file(file_path)

    return {
        "file": file_path,
        "safe": result.safe,
        "score": result.score,
        "findings": result.findings,
        "recommendation": (
            "SAFE" if result.safe
            else "DO NOT INSTALL — file contains suspicious content"
        ),
    }


# ================================================================
#  CLI
# ================================================================

if __name__ == "__main__":
    import argparse
    import sys

    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="Download Pre-Scan — Security check for external content",
    )
    parser.add_argument("file", nargs="?", help="File to scan")
    parser.add_argument("--type", choices=["skill", "mcp_config", "script", "binary", "unknown"],
                        default="unknown", help="File type for targeted checks")
    parser.add_argument("--source", default="", help="Where the content came from")
    parser.add_argument("--content", help="Scan inline content instead of a file")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if args.content:
        result = scan_before_install(args.content, file_type=args.type, source=args.source)
    elif args.file:
        result = scan_file(args.file)
    else:
        print("Usage: python download_scanner.py <file> [--type skill]")
        print("       python download_scanner.py --content '...' --type skill")
        sys.exit(1)

    if args.json:
        print(json.dumps({
            "safe": result.safe,
            "score": result.score,
            "findings": result.findings,
        }, indent=2, ensure_ascii=False))
    else:
        icon = "SAFE" if result.safe else "DANGER"
        print(f"\n  Scan Result: {icon} (score: {result.score}/100)")
        if result.findings:
            print(f"  Findings ({len(result.findings)}):")
            for f in result.findings:
                sev_icon = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵", "INFO": "⚪"}
                print(f"    {sev_icon.get(f['severity'], '?')} [{f['severity']}] {f['category']}: {f['detail'][:120]}")
