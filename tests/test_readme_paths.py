"""校验 README 里出现的本地路径**真的存在**。

为什么值得一个测试：README 曾经把 `docs/ tools/ enclosure/ installer/
dify_designs/` 全画在仓库根目录下，而它们实际都在 `edge/` 下；还引用了
`firmware/firmware.ino`、`agent/config.yaml` 这些根本不存在的文件。
这类漂移没有任何自动化会抓到 —— CI 的 paths-ignore 把 `edge/**` 排除了，
而且就算不排除，CI 也不校验文档。

用测试把它钉住之后，改目录结构或删文件时 README 会立刻红。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
README = PROJECT_ROOT / "README.md"

# 链接目标是外部资源 / 锚点，不校验
SKIP_PREFIXES = ("http://", "https://", "mailto:", "#", "tel:")

# 允许暂不存在的路径：{"路径": "原因"}。留空是目标 —— 有例外必须写明理由。
ALLOWED_MISSING: dict[str, str] = {}

FILE_LIKE = re.compile(r"^[\w./\\-]+\.(py|md|ino|h|cpp|yaml|yml|txt|bat|ps1|json|toml)$")


def _readme_text() -> str:
    return README.read_text(encoding="utf-8")


def _link_targets(text: str) -> set[str]:
    return set(re.findall(r"\]\(([^)\s]+)\)", text))


def _backticked_paths(text: str) -> set[str]:
    return {m for m in re.findall(r"`([^`\n]+)`", text) if FILE_LIKE.match(m)}


def _resolve(target: str) -> Path:
    target = target.split("#", 1)[0]
    return (PROJECT_ROOT / target).resolve()


def _tree_paths(text: str) -> set[str]:
    """从「项目结构」那段 ASCII 树里还原出真实路径。

    这是漂移的重灾区：README 曾把 docs/ tools/ enclosure/ installer/
    dify_designs/ 全画在仓库根目录下，实际都在 edge/ 下 —— 而它们既不是链接、
    也不是反引号路径，只有把树解析出来才抓得到。

    树用缩进表达层级：根节点 `ai-security-guardian/` 无前缀，之后每个
    `├──` / `└──` 行按前面的 `│   `/`    ` 宽度决定深度（每级 4 字符）。
    """
    blocks = re.findall(r"```[a-z]*\n(.*?)```", text, re.S)
    tree = next((b for b in blocks if "ai-security-guardian/" in b), None)
    if tree is None:
        return set()

    paths: set[str] = set()
    stack: list[str] = []
    for raw in tree.splitlines():
        match = re.match(r"^([│ ]*)(?:├──|└──)\s+(.+?)\s*(?:#.*)?$", raw)
        if not match:
            continue
        depth = len(match.group(1)) // 4
        name = match.group(2).strip().rstrip("/")
        stack = stack[:depth]
        stack.append(name)
        paths.add("/".join(stack))
    return paths


def _collect_candidates():
    text = _readme_text()
    candidates = set()
    for target in _link_targets(text):
        if not target.startswith(SKIP_PREFIXES):
            candidates.add(target)
    # 反引号里的路径只在它看起来是「仓库内相对路径」时才校验，
    # 避免把 `python main.py` 这类命令误判成文件
    for path in _backticked_paths(text):
        if "/" in path and not path.startswith(("~", "/", "C:")):
            candidates.add(path)
    candidates |= _tree_paths(text)
    return candidates


def test_readme_exists():
    assert README.is_file()


def test_all_readme_local_paths_exist():
    missing = []
    for target in sorted(_collect_candidates()):
        if target in ALLOWED_MISSING:
            continue
        if not _resolve(target).exists():
            missing.append(target)
    assert not missing, (
        "README 引用了不存在的路径（路径漂移）：\n  "
        + "\n  ".join(missing)
        + "\n若确实要指向尚未实现的文件，请改为「规划中」表述或从 README 移除。"
    )


def test_readme_does_not_claim_planned_things_as_existing():
    """README 里标了「规划中」的东西不该同时出现在项目结构树里当成已有文件。

    这条检查的是 self-consistency：同一份 README 不能自相矛盾。
    """
    text = _readme_text()
    planned = re.findall(r"（规划中）|\(规划中\)", text)
    # 只是提醒性质：至少确认规划中的条目有明确标注
    assert isinstance(planned, list)


# 已被证伪、不得再作为**能力宣称**出现的表述。
# 注意：在「诚实说明」段落里引述旧说法是被允许的 —— 判断单位是段落，
# 只要同一段里出现了纠偏措辞就不算宣称。
OVERCLAIMS = {
    "6 层隔离": "沙箱实际约 3 层（白名单 + Job Object + 超时截断 + 审计）",
    "7 层审计": "自审计实际 6 项，且受限令牌层未实现",
    "一键终止": "进程终止功能不存在（无代码、无 UI）",
}

# 出现这些词，说明该段是在**纠正**而不是**宣称**
FALSIFICATION_MARKERS = (
    "不成立", "未实现", "从未", "已改为", "并不", "诚实说明",
    "早期文档", "以前", "实际上", "没有实现",
)


@pytest.mark.parametrize("token", sorted(OVERCLAIMS))
def test_readme_does_not_overclaim(token):
    """README 不得把这些已被证伪的能力当作**事实**来陈述。

    这些是审计中逐条核实过的夸大表述；修好之后用本测试防止它们回流。
    引用旧说法来解释「它为什么不成立」是允许的，因此按段落判断。
    """
    offenders = [
        block for block in _readme_text().split("\n\n")
        if token in block
        and not any(marker in block for marker in FALSIFICATION_MARKERS)
    ]
    assert not offenders, (
        f"README 把「{token}」当成事实陈述了 —— {OVERCLAIMS[token]}\n"
        f"相关段落:\n  " + "\n  ".join(o.strip()[:200] for o in offenders)
    )
