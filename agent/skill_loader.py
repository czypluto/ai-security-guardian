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
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("Guardian.Skills")


def _trigger_score(trigger: str, text: str) -> int:
    """一个触发词对用户输入的匹配强度；0 表示不匹配。

    两档：

    * **连续子串**命中 -> 高分。这是最可靠的信号。
    * **字符按序散落**（子序列）命中 -> 低分。中文里修饰语常常插在词中间：
      触发词「扫描网络」理应命中「扫描我的网络」，而纯子串匹配做不到。
      这一条直接来自实测 —— 原先「扫描我的网络」匹配不到任何技能。

    子序列只对长度 >= 3 的触发词放开。否则「检查」这类两字词在几乎任何中文
    句子里都能"按序出现"，等于没有约束。
    """
    t = (trigger or "").strip().lower()
    if not t or not text:
        return 0
    if t in text:
        return 1000 + len(t)
    if len(t) < 3:
        return 0
    cursor = iter(text)
    if all(ch in cursor for ch in t):
        return len(t)
    return 0


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
        skipped: list[str] = []
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
                        else:
                            skipped.append(os.path.relpath(full_path, skill_dir))
        logger.info(f"Skills: loaded {len(self._skills)} from {len(self._skill_dirs)} dirs "
                    f"({list(self._skills.keys())})")
        if skipped:
            logger.info("Skills: 跳过 %d 个非技能 .md（无 triggers）: %s",
                        len(skipped), skipped)
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

        # triggers 允许两种写法：YAML 列表，或一行逗号分隔的字符串。
        # 原实现把逗号字符串整体当成**一个**触发器（"白名单, whitelist, ..."），
        # 那种写法实际永远匹配不上。
        triggers = frontmatter.get("triggers", [])
        if isinstance(triggers, str):
            triggers = [t.strip() for t in triggers.split(",") if t.strip()]
        if not isinstance(triggers, list):
            triggers = [triggers]

        if not triggers:
            # 没有触发器 = 永远不可能被激活。加载它只会污染「可用技能」列表、
            # 白占系统提示词的位置，还会让匹配逻辑在宽泛词上误命中。
            # os.walk 是递归的，所以技能包里的 references/*.md 资料文件、
            # 以及只有 name/description 的 SKILL.md 都会走到这里。
            logger.debug("跳过非技能 .md（无 triggers）: %s", file_path)
            return None

        return Skill(
            name=name,
            description=description,
            content=body,
            triggers=triggers,
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
        """选出一轮里最匹配的技能。

        取**得分最高**者，而不是第一个命中者。原实现是「第一个命中即返回」，
        于是激活哪个技能取决于 dict 的迭代顺序 —— 触发词一旦有重复，结果就
        不可预期（实测「可疑进程」曾同时属于两个技能）。

        现在按 (得分降序, 技能名) 排序，同样的输入永远得到同样的结果。
        """
        text = (user_input or "").lower()
        if not text:
            return None

        scored = []
        for skill in self._skills.values():
            score = max((_trigger_score(t, text) for t in skill.triggers), default=0)
            if score:
                scored.append((score, skill.name, skill))
        if not scored:
            return None
        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored[0][2]

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
