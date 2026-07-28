"""
Self-Install Tools — agent/installer.py

Lets the agent install its own skills (.md files) and recommend MCP servers.
This is the ONLY file that can write to the filesystem.

SECURITY MODEL (enforced in code, not just in prompt):
  ALLOWED:   Write .md files to skills/  (markdown, never executed)
  ALLOWED:   List installed skills
  BLOCKED:   Modify config.yaml          (would allow arbitrary MCP code)
  BLOCKED:   Modify agent/*.py           (would allow code injection)
  BLOCKED:   Write outside skills/       (path whitelist)
  BLOCKED:   Access .env                 (credential theft)
  BLOCKED:   Auto-install MCP servers    (user must manually review)
  BLOCKED:   Skill content with code patterns (os.system, subprocess, exec...)

Design principle: Skills are safe because they're just markdown injected into
the LLM prompt. They cannot execute code. MCP servers CAN execute code, so
they require manual user approval.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("Guardian.Installer")

# Only these directories are writable
SKILLS_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "skills")
)
ALLOWED_WRITE_DIRS = [os.path.normpath(SKILLS_DIR)]

# Never allow writing to these paths
BLOCKED_PATHS = [
    "config.yaml", ".env", "agent/", "pc_agent/", "mcp_server/",
    "__pycache__", ".git", "venv", ".venv", "node_modules",
]


def _is_path_safe(file_path: str) -> tuple[bool, str]:
    """Validate a write path is within the allowed skills directory."""
    try:
        resolved = os.path.normpath(os.path.abspath(file_path))
    except Exception:
        return False, "invalid path"

    # Must be inside the project directory
    project_root = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..")
    )
    if not resolved.startswith(project_root):
        return False, "path outside project"

    # Must not touch blocked paths
    rel = os.path.relpath(resolved, project_root)
    for blocked in BLOCKED_PATHS:
        if rel.startswith(blocked) or blocked in rel.split(os.sep):
            return False, f"blocked path: {blocked}"

    # Must be in skills/ directory
    in_allowed = any(resolved.startswith(d) for d in ALLOWED_WRITE_DIRS)
    if not in_allowed:
        return False, "not in skills/ directory"

    return True, "ok"


# ================================================================
#  Safe install tools
# ================================================================

def install_skill(name: str, description: str, content: str,
                  triggers: str = "") -> dict:
    """
    Install a skill by writing a .md file to skills/.

    SAFE: Skills are pure markdown text injected into the system prompt.
    They are NEVER executed as code. The worst a malicious skill can do
    is add bad instructions to the prompt — which is harmless because
    the LLM cannot modify core code or config.
    """
    if not name or not content:
        return {"success": False, "error": "name and content required"}

    # Sanitize filename: only a-z, 0-9, -, _
    safe_name = "".join(c for c in name.lower() if c.isalnum() or c in "-_")
    if not safe_name or len(safe_name) > 64:
        return {"success": False, "error": f"invalid skill name: {name}"}

    file_path = os.path.join(SKILLS_DIR, f"{safe_name}.md")

    # Security check
    allowed, reason = _is_path_safe(file_path)
    if not allowed:
        logger.warning(f"Skill install blocked: {file_path} — {reason}")
        return {"success": False, "error": f"Path blocked: {reason}"}

    # Content sanitization: reject anything that looks like code injection
    content_lower = content.lower()
    dangerous = [
        "os.system", "subprocess", "exec(", "eval(", "__import__",
        "rm -rf", "del /f", "format c:", "shutdown",
    ]
    for pattern in dangerous:
        if pattern in content_lower:
            return {"success": False,
                    "error": f"Dangerous content detected: '{pattern}'"}

    # Build frontmatter
    trigger_list = [t.strip() for t in triggers.split(",") if t.strip()]
    trigger_yaml = "\n".join(f'  - "{t}"' for t in trigger_list)

    frontmatter = f"""---
name: {safe_name}
description: {description}
triggers:
{trigger_yaml if trigger_yaml else '  - "' + safe_name + '"'}
---
"""

    # Write
    try:
        os.makedirs(SKILLS_DIR, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(frontmatter + "\n" + content)
        logger.info(f"Skill installed: {safe_name} -> {file_path}")
        return {
            "success": True,
            "skill_name": safe_name,
            "file": file_path,
            "message": (f"Skill '{safe_name}' installed. Restart the agent "
                        f"or type /skills to see it. Trigger it by saying "
                        f"one of: {trigger_list or [safe_name]}"),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def recommend_mcp_server(name: str, install_command: str,
                         description: str) -> dict:
    """
    Search for and recommend an MCP server. Does NOT install automatically.

    SECURITY: MCP servers can execute arbitrary code. The user must review
    and manually add to config.yaml. This tool only provides instructions.
    """
    if not name or not install_command:
        return {"success": False, "error": "name and install_command required"}

    # Generate config snippet for the user
    config_snippet = f"""  - name: {name}
    transport: stdio
    command: "{install_command}"
    # {description}"""

    return {
        "success": True,
        "note": "⚠️  MCP servers are NOT auto-installed for security. "
                "They can execute arbitrary code. Please review and "
                "manually add to pc_agent/config.yaml → mcp_servers:",
        "config_snippet": config_snippet,
        "steps": [
            f"1. Review this MCP server: {description}",
            f"2. Verify the install command: {install_command}",
            "3. Open pc_agent/config.yaml",
            "4. Add the snippet under mcp_servers:",
            "5. Restart the agent",
        ],
    }


def list_installed_skills() -> dict:
    """List all currently installed skills."""
    skills = []
    if os.path.isdir(SKILLS_DIR):
        for fname in sorted(os.listdir(SKILLS_DIR)):
            if fname.endswith(".md"):
                fpath = os.path.join(SKILLS_DIR, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        first_lines = "".join(f.readline() for _ in range(5))
                except Exception:
                    first_lines = "(read error)"
                skills.append({
                    "name": fname.replace(".md", ""),
                    "file": fname,
                    "preview": first_lines[:200],
                })
    return {"skills_dir": SKILLS_DIR, "count": len(skills), "skills": skills}
