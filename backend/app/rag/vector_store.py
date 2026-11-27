"""Tiny local vector store (TF-IDF + cosine). No dependencies, fully offline."""
from __future__ import annotations

import math
import re
from collections import Counter

from app.observability import recorder as observe

_STOP = {
    "the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "for", "with", "is", "are", "was", "it",
    "this", "that", "by", "from", "as", "be", "its", "has", "have", "you", "your", "can", "will",
}
_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


class KnowledgeBase:
    def __init__(self) -> None:
        self.docs: list[dict] = []

    def add(self, text: str, **meta) -> None:
        self.docs.append({"text": text, "tokens": Counter(tokenize(text)), "meta": meta})

    def _idf(self) -> dict[str, float]:
        n = len(self.docs) or 1
        df: Counter = Counter()
        for d in self.docs:
            df.update(d["tokens"].keys())
        return {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}

    def query(self, q: str, k: int = 3) -> list[dict]:
        with observe.span("retrieval", "local_text_search") as step:
            hits = self._search(q, k)
            step.set(documents=len(self.docs), results=len(hits), top_score=hits[0]["score"] if hits else 0)
            if not hits:
                step.status = "empty"
            if hits:
                step.detail("results", [str(h.get("text", ""))[:300] for h in hits])
            return hits

    def _search(self, q: str, k: int) -> list[dict]:
        if not self.docs:
            return []
        idf = self._idf()
        qv = Counter(tokenize(q))
        if not qv:
            return []

        def vec(counts):
            return {t: c * idf.get(t, 1.0) for t, c in counts.items()}

        qvec = vec(qv)
        qn = math.sqrt(sum(v * v for v in qvec.values())) or 1.0
        scored = []
        for d in self.docs:
            dvec = vec(d["tokens"])
            dn = math.sqrt(sum(v * v for v in dvec.values())) or 1.0
            dot = sum(qvec[t] * dvec.get(t, 0.0) for t in qvec)
            score = dot / (qn * dn)
            if score > 0:
                scored.append((score, d))
        scored.sort(key=lambda x: -x[0])
        return [{"text": d["text"], "score": round(s, 4), **d["meta"]} for s, d in scored[:k]]
