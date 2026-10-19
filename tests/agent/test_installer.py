"""installer 路径白名单测试。

这是本产品**唯一的写文件入口**，所以路径判定值得钉死。
修之前这里有两个问题（见下面标了「回归」的两条）：
  1. 用 `str.startswith` 判目录包含 → `<root>-evil/` 能绕过
  2. BLOCKED_PATHS 里带正斜杠的条目在 Windows 上匹配不上（rel 用反斜杠）
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agent.installer import (  # noqa: E402
    ALLOWED_WRITE_DIRS,
    BLOCKED_PATHS,
    SKILLS_DIR,
    _is_path_safe,
    _within,
)

PROJECT_ROOT = os.path.dirname(SKILLS_DIR)      # SKILLS_DIR = <root>/skills


# ---- _within：目录包含判断 ----

def test_within_accepts_real_subpath():
    assert _within(os.path.join(PROJECT_ROOT, "skills", "user", "a.md"), PROJECT_ROOT)
    assert _within(SKILLS_DIR, PROJECT_ROOT)


def test_within_rejects_sibling_with_shared_prefix(tmp_path):
    """回归：字符串前缀判断会把 `<parent>-evil` 当成子目录。

    修前实现是 `resolved.startswith(project_root)`，
    `/x/ai-security-guardian-evil/a.md` 会通过 —— 因为它确实以
    `/x/ai-security-guardian` 开头。
    """
    root = tmp_path / "proj"
    evil = tmp_path / "proj-evil"
    root.mkdir()
    evil.mkdir()
    assert not _within(str(evil / "a.md"), str(root))


def test_within_rejects_parent_and_unrelated(tmp_path):
    inner = tmp_path / "proj" / "skills"
    inner.mkdir(parents=True)
    assert not _within(str(tmp_path), str(inner))          # 父目录不是子目录
    other = tmp_path / "other"
    other.mkdir()
    assert not _within(str(other), str(inner))


def test_within_cross_drive_does_not_raise():
    """跨盘符时 commonpath 抛 ValueError，必须吞掉并返回 False 而不是崩。"""
    assert _within("D:/x.md", "C:/proj") is False


# ---- _is_path_safe ----

def test_allows_write_inside_skills():
    ok, why = _is_path_safe(os.path.join(SKILLS_DIR, "user", "note.md"))
    assert ok, why


def test_rejects_sibling_with_shared_prefix():
    """回归：`<root>-evil/` 曾经能拿到 ALLOW。"""
    evil = os.path.normpath(os.path.join(PROJECT_ROOT + "-evil", "skills", "a.md"))
    ok, why = _is_path_safe(evil)
    assert not ok and "outside project" in why, why


def test_rejects_paths_outside_project(tmp_path):
    ok, why = _is_path_safe(str(tmp_path / "a.md"))
    assert not ok and "outside project" in why, why


def test_blocked_paths_are_blocked_for_the_right_reason():
    """回归：带斜杠的黑名单条目在 Windows 上匹配不上，会被更严的
    "not in skills/" 兜住 —— 拦截生效但不是靠黑名单。这里要求
    拦截理由必须是黑名单本身，否则那条防线等于没在守。"""
    for blocked in BLOCKED_PATHS:
        name = blocked.rstrip("/\\")
        path = os.path.join(PROJECT_ROOT, name, "x.md")
        ok, why = _is_path_safe(path)
        assert not ok, f"{blocked} 应当被拒"
        assert "blocked path" in why, f"{blocked} 的拒绝理由不对：{why}"


def test_dot_env_is_blocked():
    ok, why = _is_path_safe(os.path.join(PROJECT_ROOT, ".env"))
    assert not ok and "blocked path" in why, why


def test_cross_drive_returns_false_not_crash():
    ok, why = _is_path_safe("D:/evil/x.md")
    assert not ok, why


def test_allowed_write_dirs_nonempty():
    """白名单为空会让函数退化成「什么都允许」，钉一下。"""
    assert ALLOWED_WRITE_DIRS
    assert os.path.isdir(SKILLS_DIR), f"skills 目录不存在：{SKILLS_DIR}"
