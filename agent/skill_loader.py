"""
Skill Loader — Auto-discover and inject .md skill files.

Like Claude Code, skills are markdown files with YAML frontmatter.
Drop a .md file into skills/ → agent picks it up automatically.

Format:
  ---
  name: network-audit
  description: Deep network security audit
  triggers:
    - "scan network"
    - "check network"
  ---
  # Skill content (injected into system prompt)
  ...
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("Guardian.Skills")


@dataclass
class Skill:
    name: str
    description: str
    content: str          # Full markdown body (without frontmatter)
    triggers: list[str] = field(default_factory=list)
    file_path: str = ""

    @property
    def prompt_injection(self) -> str:
        """Format skill content for system prompt injection."""
        return (
            f"<skill name=\"{self.name}\">\n"
            f"  <description>{self.description}</description>\n"
            f"  <instructions>\n{self.content}\n  </instructions>\n"
            f"</skill>\n"
        )


class SkillManager:
    """Load and manage skills from filesystem."""

    def __init__(self, skill_dirs: list[str] = None):
        self._skill_dirs = skill_dirs or []
        self._skills: dict[str, Skill] = {}

    def add_directory(self, path: str):
        """Add a directory to scan for .md skill files."""
        if path not in self._skill_dirs:
            self._skill_dirs.append(path)

    def load_all(self) -> list[Skill]:
        """Scan all directories and load discovered skills."""
        self._skills.clear()
        for skill_dir in self._skill_dirs:
            if not os.path.isdir(skill_dir):
                continue
            for root, _, files in os.walk(skill_dir):
                for fname in files:
                    if fname.endswith(".md"):
                        full_path = os.path.join(root, fname)
                        skill = self._parse_skill_file(full_path)
                        if skill:
                            self._skills[skill.name] = skill
        logger.info(f"Skills: loaded {len(self._skills)} from {len(self._skill_dirs)} dirs "
                    f"({list(self._skills.keys())})")
        return self.list_all()

    def _parse_skill_file(self, file_path: str) -> Optional[Skill]:
        """Parse a single .md skill file with YAML frontmatter."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            logger.warning(f"Skill read error: {file_path}: {e}")
            return None

        # Parse YAML frontmatter (--- ... ---)
        frontmatter = {}
        body = content
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                frontmatter = self._parse_simple_yaml(parts[1])
                body = parts[2].strip()

        name = frontmatter.get("name", os.path.splitext(os.path.basename(file_path))[0])
        description = frontmatter.get("description", body[:120].replace("\n", " "))
        triggers = frontmatter.get("triggers", [])

        return Skill(
            name=name,
            description=description,
            content=body,
            triggers=triggers if isinstance(triggers, list) else [triggers],
            file_path=file_path,
        )

    @staticmethod
    def _parse_simple_yaml(text: str) -> dict:
        """Super-simple YAML parser for frontmatter (no PyYAML dependency)."""
        result = {}
        current_key = None
        current_list = None

        for line in text.strip().split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # Key: value
            if ":" in stripped and not stripped.startswith("- "):
                # Finish previous list
                if current_list is not None and current_key:
                    result[current_key] = current_list
                    current_list = None

                key, _, val = stripped.partition(":")
                key, val = key.strip(), val.strip()
                if val:
                    result[key] = val.strip('"').strip("'")
                else:
                    current_key = key
                    current_list = []
            # List item
            elif stripped.startswith("- ") and current_key:
                item = stripped[2:].strip().strip('"').strip("'")
                if current_list is not None:
                    current_list.append(item)
            else:
                if current_list is not None and current_key:
                    result[current_key] = current_list
                    current_list = None
                current_key = None

        if current_list is not None and current_key:
            result[current_key] = current_list

        return result

    def list_all(self) -> list[Skill]:
        return list(self._skills.values())

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def match_triggers(self, user_input: str) -> Optional[Skill]:
        """Find a skill whose triggers match the user input."""
        user_lower = user_input.lower()
        for skill in self._skills.values():
            for trigger in skill.triggers:
                if trigger.lower() in user_lower:
                    return skill
        return None

    def build_skills_prompt(self, matched_skill: Skill = None) -> str:
        """Build the skills section of the system prompt."""
        parts = []
        if matched_skill:
            parts.append("## Active Skill\n")
            parts.append(matched_skill.prompt_injection)
            parts.append("Follow the skill instructions above.\n")
        else:
            parts.append("## Available Skills\n")
            parts.append("Mention a trigger phrase to activate:\n")
            for skill in self._skills.values():
                triggers_str = ", ".join(f'"{t}"' for t in skill.triggers[:3])
                parts.append(f"- **{skill.name}**: {skill.description}")
                parts.append(f"  Triggers: {triggers_str}\n")
        return "\n".join(parts)
