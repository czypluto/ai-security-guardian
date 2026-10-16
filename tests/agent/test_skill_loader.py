"""测试 agent/skill_loader.py: 技能发现、frontmatter 解析、触发词约束。

背景：`os.walk` 是递归的，技能包里的 `references/*.md` 资料文件、以及只有
name/description 的 SKILL.md 都会被当成技能加载。实测有 4 个这样的文件混进
「可用技能」列表 —— 它们没有 triggers，永远不可能被激活，只是白占系统提示词的位置，
还会让宽泛触发词互相劫持。
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from agent.skill_loader import SkillManager

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
REAL_SKILLS_DIR = PROJECT_ROOT / "skills"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


@pytest.fixture
def skill_tree(tmp_path):
    """一个典型的技能目录：真技能 + 嵌套的资料文件 + 无 triggers 的 SKILL.md。"""
    _write(tmp_path / "real.md", """\
        ---
        name: real-skill
        description: A real skill
        triggers:
          - "hello"
        ---

        # Real
        正文
        """)
    _write(tmp_path / "no-triggers.md", """\
        ---
        name: no-triggers
        description: 有 frontmatter 但没有 triggers
        ---

        # 永远不会被激活
        """)
    _write(tmp_path / "plain-doc.md", """\
        # 纯资料，没有 frontmatter
        这是一份说明文档，不是技能。
        """)
    _write(tmp_path / "pack" / "SKILL.md", """\
        ---
        name: pack
        description: 技能包主文件但没有 triggers
        ---
        """)
    _write(tmp_path / "pack" / "references" / "deep.md", """\
        # 参考资料
        藏在 references/ 里，不该被当成技能。
        """)
    _write(tmp_path / "comma.md", """\
        ---
        name: comma-skill
        description: triggers 写成一行逗号分隔
        triggers: 甲, 乙, 丙
        ---

        # Comma
        """)
    return tmp_path


class TestSkillDiscovery:
    def test_only_files_with_triggers_become_skills(self, skill_tree):
        names = {s.name for s in SkillManager([str(skill_tree)]).load_all()}
        assert names == {"real-skill", "comma-skill"}

    def test_nested_reference_docs_are_skipped(self, skill_tree):
        names = {s.name for s in SkillManager([str(skill_tree)]).load_all()}
        assert "deep" not in names
        assert "plain-doc" not in names
        assert "no-triggers" not in names
        assert "pack" not in names

    def test_comma_separated_triggers_are_split(self, skill_tree):
        """`triggers: 甲, 乙, 丙` 曾整体被当成**一个**触发器，那种写法永远匹配不上。"""
        skills = {s.name: s for s in SkillManager([str(skill_tree)]).load_all()}
        assert skills["comma-skill"].triggers == ["甲", "乙", "丙"]


@pytest.fixture(scope="module")
def skills():
    return SkillManager([str(REAL_SKILLS_DIR), str(REAL_SKILLS_DIR / "user")]).load_all()


class TestRealSkillsDirectory:
    """对仓库里真实的 skills/ 施加约束。"""

    def test_loads_something(self, skills):
        assert len(skills) >= 5

    def test_every_loaded_skill_has_triggers(self, skills):
        for s in skills:
            assert s.triggers, f"{s.name} 没有 triggers，不该被加载"

    def test_no_trigger_is_shared_between_skills(self, skills):
        """触发词不得重复。

        match_triggers 取**第一个**命中者，重复触发词会让「激活了哪个技能」
        取决于字典序 —— 实测「可疑进程」曾同时属于 process-whitelist 与
        process-check。
        """
        owner: dict[str, list[str]] = {}
        for s in skills:
            for t in s.triggers:
                owner.setdefault(t.lower(), []).append(s.name)
        collisions = {t: names for t, names in owner.items() if len(names) > 1}
        assert not collisions, f"触发词重复: {collisions}"

    def test_broad_keywords_are_not_used_as_triggers(self, skills):
        """「扫描」「检查」这类词出现在任何安全查询里，不能拿来当触发词 ——
        否则会劫持本该命中 network-scan / ransomware-check 的提问。"""
        hijackers = {"scan", "扫描", "检查", "威胁", "网络", "进程"}
        offenders = [
            (s.name, t) for s in skills for t in s.triggers
            if t.lower() in hijackers
        ]
        assert not offenders, f"触发词过宽: {offenders}"

    def test_no_file_has_duplicated_frontmatter(self):
        """process-whitelist.md 曾有两段 frontmatter；解析器只取第一段，
        第二段的文本会漏进正文。"""
        for path in REAL_SKILLS_DIR.rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            if not text.startswith("---"):
                continue
            body = text.split("---", 2)[2] if text.count("---") >= 2 else ""
            assert not body.lstrip().startswith("---\nname:"), \
                f"{path} 正文里残留了第二段 frontmatter"
