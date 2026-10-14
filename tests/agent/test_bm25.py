"""测试 agent/bm25.py 与知识库的混合检索（向量路 + 中文 BM25 路 + RRF 融合）。

全部离线：不起 Milvus/Qdrant/vLLM，嵌入显式关闭，走纯 Python 的 BM25 路径。
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

# 与其他 agent 测试一致：先屏蔽 Windows 专用模块
_mock_ctypes = MagicMock()
_mock_ctypes.windll = MagicMock()
_mock_ctypes.windll.kernel32 = MagicMock()
_mock_ctypes.windll.shell32 = MagicMock()
_mock_ctypes.windll.shell32.IsUserAnAdmin = MagicMock(return_value=False)
_mock_ctypes.wintypes = MagicMock()
_mock_ctypes.Structure = type
sys.modules.setdefault("ctypes", _mock_ctypes)

from agent.bm25 import Bm25Index, rrf_fuse, rrf_scores, tokenize  # noqa: E402


# ---------------- 切词 ----------------

def test_tokenize_cjk_uses_overlapping_bigram():
    assert tokenize("防火墙") == ["防火", "火墙"]


def test_tokenize_keeps_latin_words_and_numbers():
    toks = tokenize("netsh advfirewall 4625")
    assert "netsh" in toks and "advfirewall" in toks and "4625" in toks


def test_tokenize_mixed_and_single_char():
    assert tokenize("查 4625") == ["4625", "查"]
    assert tokenize("") == []


def test_tokenize_is_case_insensitive():
    assert tokenize("NETSH") == tokenize("netsh")


# ---------------- BM25 ----------------

def _corpus() -> Bm25Index:
    return Bm25Index().build({
        "a_0": "可疑连接 122.192.134.252 端口 8080 腾讯会议",
        "a_1": "防火墙检查 netsh advfirewall 显示三个配置文件已开启",
        "b_0": "学生票 乘车区间 优惠卡 寒暑假",
    })


def test_bm25_ranks_the_matching_chunk_first():
    hits = _corpus().search("防火墙 netsh", top_k=3)
    assert hits
    assert hits[0][0] == "a_1"


def test_bm25_rewards_rare_terms_over_common_ones():
    """出现在所有文档里的词区分度应当更低（idf 的作用）。"""
    idx = Bm25Index().build({
        "d1": "端口 端口 端口 防火墙",
        "d2": "端口 连接",
    })
    scores = dict(idx.search("端口 防火墙", top_k=2))
    assert scores["d1"] > scores["d2"]


def test_bm25_is_deterministic_on_ties():
    docs = {f"d{i}": "完全一样的词" for i in range(5)}
    first = Bm25Index().build(docs).search("完全一样的词", top_k=5)
    second = Bm25Index().build(docs).search("完全一样的词", top_k=5)
    assert first == second
    assert [doc_id for doc_id, _ in first] == sorted(docs)  # 并列按 doc_id 定序


def test_bm25_allow_filters_candidates():
    hits = _corpus().search("端口", top_k=5, allow=["a_1"])
    assert all(doc_id == "a_1" for doc_id, _ in hits)


def test_bm25_edge_cases():
    assert _corpus().search("", top_k=3) == []
    assert _corpus().search("完全不相关的词", top_k=3) == []
    assert Bm25Index().build({}).search("任意", top_k=3) == []


# ---------------- RRF ----------------

def test_rrf_prefers_document_hit_by_both_paths():
    order = rrf_fuse([["x", "y"], ["y", "z"]])
    assert order[0] == "y"


def test_rrf_single_ranking_keeps_order():
    assert rrf_fuse([["a", "b", "c"]]) == ["a", "b", "c"]


def test_rrf_deterministic_on_ties():
    assert rrf_fuse([["a"], ["b"]]) == ["a", "b"]


def test_rrf_scores_expose_the_fused_value():
    """融合后对外给的是 RRF 分，不是某一来源路的原始分（量纲不同，不能混着用）。"""
    scores = rrf_scores([["x", "y"], ["y", "z"]])
    # y 两路都命中：rank 2 与 rank 1 各得 1/(60+2) + 1/(60+1)
    assert scores["y"] == pytest.approx(1 / 62 + 1 / 61)
    assert scores["y"] > scores["x"] and scores["y"] > scores["z"]


# ---------------- 知识库混合检索（离线） ----------------

_MD_1 = """---
timestamp: 2026-08-01T10:00:00
topics: ["防火墙", "网络扫描"]
---

# AI Security Guardian — 对话记录

**User**:
怎么检查防火墙是否开启

**安小盾**:
运行 netsh advfirewall show allprofiles，可以查看三个配置文件的启用状态。
"""

_MD_2 = """---
timestamp: 2026-08-01T11:00:00
topics: ["威胁情报"]
---

# AI Security Guardian — 对话记录

**User**:
这个 IP 122.192.134.252 可信吗

**安小盾**:
已查 OTX 威胁情报：该 IP 未被标记为恶意，但它通过 8080 端口建立 HTTP 隧道，值得关注。
"""


def _kb(tmp_path):
    """构造一个没有向量库的知识库——正是 Milvus/Qdrant 没起时的真实状态。"""
    from agent.knowledge_base import KnowledgeBase
    d = tmp_path / "conversations"
    d.mkdir(parents=True)
    (d / "2026-08-01_100000.md").write_text(_MD_1, encoding="utf-8")
    (d / "2026-08-01_110000.md").write_text(_MD_2, encoding="utf-8")
    return KnowledgeBase(persist_dir=str(tmp_path),
                         embedding_cfg={"enabled": False})  # 不探测 vLLM，走纯离线


def test_bm25_index_is_built_from_markdown(tmp_path):
    kb = _kb(tmp_path)
    assert len(kb._ensure_bm25_index()) == 2  # 每个文件一个 Q&A 分块


def test_search_still_hits_without_vector_store(tmp_path):
    """向量库不可用时检索仍应命中——这是依赖服务没起时的真实场景。"""
    kb = _kb(tmp_path)
    assert kb._store_ready is False
    hits = kb.search("netsh advfirewall", top_k=3)
    assert hits
    assert "netsh" in hits[0]["text"]
    assert hits[0]["metadata"]["source"].endswith(".md")


def test_search_hits_exact_terms_vectors_are_weak_at(tmp_path):
    """精确编号/术语是 BM25 的强项。"""
    kb = _kb(tmp_path)
    hits = kb.search("122.192.134.252", top_k=3)
    assert hits
    assert "122.192.134.252" in hits[0]["text"]


def test_index_is_invalidated_after_adding_conversation(tmp_path):
    kb = _kb(tmp_path)
    assert len(kb._ensure_bm25_index()) == 2
    kb.add_conversation([
        {"role": "user", "content": "行李怎么托运"},
        {"role": "assistant", "content": "按规定办理托运手续，超重部分核收运费"},
    ])
    assert len(kb._ensure_bm25_index()) == 3


def test_index_is_invalidated_after_delete(tmp_path):
    kb = _kb(tmp_path)
    assert len(kb._ensure_bm25_index()) == 2
    kb.delete_conversation("2026-08-01_100000")
    assert len(kb._ensure_bm25_index()) == 1
