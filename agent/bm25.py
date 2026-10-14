"""中文 BM25 —— 知识库的「关键词路」，与向量路做 RRF 融合。

为什么要自己写：
- **不引入分词依赖**。jieba 会带一份词典进去，对一个小工具太重；中文用 CJK 重叠 bigram
  切词即可稳定命中术语与固定搭配。
- **与向量路互补**。向量懂语义，但对精确术语、编号、命令不敏感
  （"EventID 4625"、"netsh advfirewall"、"allowlist"），BM25 的词面命中正好补这一块。

口径与铁路购票系统的同款实现保持一致（同一套切词与 RRF 公式），便于两处对照讲解。
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

_CJK = re.compile(r"[一-鿿]")
_ALNUM = re.compile(r"[a-zA-Z0-9_]+")


def _flush_cjk(run: List[str], out: List[str]) -> None:
    """把一段连续中文转成重叠 bigram；单字则原样保留。"""
    if len(run) == 1:
        out.append(run[0])
    elif len(run) >= 2:
        out.extend(run[i] + run[i + 1] for i in range(len(run) - 1))


def tokenize(text: str) -> List[str]:
    """切词：中文用重叠 bigram，拉丁字母/数字按词。无第三方依赖。

    >>> tokenize("netsh 防火墙 4625")
    ['netsh', '4625', '防火', '火墙']
    """
    if not text:
        return []
    text = text.lower()
    tokens: List[str] = _ALNUM.findall(text)
    run: List[str] = []
    for ch in text:
        if _CJK.match(ch):
            run.append(ch)
        else:
            _flush_cjk(run, tokens)
            run = []
    _flush_cjk(run, tokens)
    return tokens


class Bm25Index:
    """块级 BM25 索引。k1=1.5、b=0.75 为经典取值。"""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._tf: Dict[str, Counter] = {}
        self._len: Dict[str, int] = {}
        self._df: Counter = Counter()
        self._avgdl: float = 0.0

    def build(self, documents: Dict[str, str]) -> "Bm25Index":
        """documents: {doc_id: text}。重复 build 会整体重建。"""
        self._tf, self._len, self._df = {}, {}, Counter()
        for doc_id, text in documents.items():
            tf = Counter(tokenize(text))
            self._tf[doc_id] = tf
            self._len[doc_id] = sum(tf.values())
            for term in tf:
                self._df[term] += 1
        total = len(self._tf)
        self._avgdl = (sum(self._len.values()) / total) if total else 0.0
        return self

    def __len__(self) -> int:
        return len(self._tf)

    def search(self, query: str, top_k: int = 5,
               allow: Optional[Iterable[str]] = None) -> List[Tuple[str, float]]:
        """返回 [(doc_id, score)]，按分数降序。

        并列时按 doc_id 定序 —— 保证同一输入两次跑出完全一样的结果（可复现）。
        `allow` 用于外部过滤（如按话题筛选），None 表示不过滤。
        """
        if not self._tf:
            return []
        terms = tokenize(query)
        if not terms:
            return []
        allow_set = None if allow is None else set(allow)
        n = len(self._tf)
        avgdl = self._avgdl or 1.0
        scored: List[Tuple[str, float]] = []
        for doc_id, tf in self._tf.items():
            if allow_set is not None and doc_id not in allow_set:
                continue
            dl = self._len[doc_id] or 1
            score = 0.0
            for term in terms:
                f = tf.get(term, 0)
                if not f:
                    continue
                df = self._df.get(term, 0)
                idf = math.log(1.0 + (n - df + 0.5) / (df + 0.5))
                score += idf * (f * (self.k1 + 1.0)) / (
                    f + self.k1 * (1.0 - self.b + self.b * dl / avgdl))
            if score > 0:
                scored.append((doc_id, score))
        scored.sort(key=lambda x: (-x[1], x[0]))
        return scored[:top_k]


def rrf_scores(rankings: Sequence[Sequence[str]], k: int = 60) -> Dict[str, float]:
    """计算 RRF 分：score(d) = Σ 1/(k + rank_d)。

    只用**排名**、不用分数：两路分数量纲完全不同（余弦 0~1，BM25 0~数十），
    直接加权求和得先归一化，而归一化方式本身又是要调的超参。RRF 天然免疫量纲问题。
    k=60 是原论文的经验值，现已成为事实标准。
    """
    scores: Dict[str, float] = {}
    for ranking in rankings:
        for idx, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + idx + 1)
    return scores


def rrf_fuse(rankings: Sequence[Sequence[str]], k: int = 60) -> List[str]:
    """RRF 融合多路排名，返回按 RRF 分降序的 id（并列按 id 定序，保证可复现）。"""
    scores = rrf_scores(rankings, k)
    return sorted(scores, key=lambda d: (-scores[d], d))
