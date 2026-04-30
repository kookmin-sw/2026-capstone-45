"""SearchRecord 기반 로컬 BM25 검색 어댑터.

첫 구현에서는 외부 BM25 계층 대신 로컬 메모리 기반 BM25 scorer를 사용한다.
인터페이스는 분리해 두어 이후 HTTP/서비스형 backend로 교체할 수 있게 만든다.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Protocol, Sequence


REGEX_TOKEN = re.compile(r"[0-9A-Za-z가-힣]+")


def tokenize_text(text: str) -> list[str]:
    return [token.lower() for token in REGEX_TOKEN.findall(text or "") if token]


@dataclass(slots=True)
class BM25Document:
    record_id: str
    document_id: str
    page_id: int
    block_id: str
    text: str


@dataclass(slots=True)
class BM25Hit:
    record_id: str
    score: float
    matched_terms: list[str]
    document_id: str
    page_id: int
    block_id: str


class BM25SearchClient(Protocol):
    def search(self, query: str, docs: Sequence[str], top_k: int) -> list[BM25Hit]:
        ...


class LocalBM25SearchClient:
    """SearchRecord를 BM25 문서로 변환해 로컬에서 검색한다."""

    def __init__(self, documents: Sequence[BM25Document]):
        self.documents = list(documents)
        self._doc_tokens: dict[str, list[str]] = {}
        self._doc_term_freq: dict[str, dict[str, int]] = {}
        self._doc_lengths: dict[str, int] = {}
        self._doc_freq: dict[str, int] = {}
        self._documents_by_record_id: dict[str, BM25Document] = {}

        total_length = 0
        for document in self.documents:
            tokens = tokenize_text(document.text)
            term_freq: dict[str, int] = {}
            for token in tokens:
                term_freq[token] = term_freq.get(token, 0) + 1

            self._doc_tokens[document.record_id] = tokens
            self._doc_term_freq[document.record_id] = term_freq
            self._doc_lengths[document.record_id] = len(tokens)
            self._documents_by_record_id[document.record_id] = document
            total_length += len(tokens)

            for token in term_freq:
                self._doc_freq[token] = self._doc_freq.get(token, 0) + 1

        self._doc_count = len(self.documents)
        self._avg_doc_len = (total_length / self._doc_count) if self._doc_count else 0.0
        self.k1 = 1.5
        self.b = 0.75

    def search(self, query: str, docs: Sequence[str], top_k: int) -> list[BM25Hit]:
        query_tokens = tokenize_text(query)
        if not query_tokens or top_k <= 0:
            return []

        doc_filter = set(docs)
        scored_hits: list[BM25Hit] = []
        for document in self.documents:
            if doc_filter and document.document_id not in doc_filter:
                continue

            score = self._score_document(document.record_id, query_tokens)
            if score <= 0.0:
                continue

            matched_terms = sorted(
                {token for token in query_tokens if token in self._doc_term_freq[document.record_id]}
            )
            scored_hits.append(
                BM25Hit(
                    record_id=document.record_id,
                    score=score,
                    matched_terms=matched_terms,
                    document_id=document.document_id,
                    page_id=document.page_id,
                    block_id=document.block_id,
                )
            )

        scored_hits.sort(
            key=lambda hit: (
                -hit.score,
                hit.document_id,
                hit.page_id,
                hit.block_id,
            )
        )
        return scored_hits[:top_k]

    def _score_document(self, record_id: str, query_tokens: Sequence[str]) -> float:
        if self._doc_count == 0:
            return 0.0

        doc_len = self._doc_lengths.get(record_id, 0)
        term_freq = self._doc_term_freq.get(record_id, {})
        if doc_len == 0 or not term_freq:
            return 0.0

        score = 0.0
        for token in query_tokens:
            freq = term_freq.get(token, 0)
            if freq <= 0:
                continue

            doc_freq = self._doc_freq.get(token, 0)
            idf = math.log(1.0 + ((self._doc_count - doc_freq + 0.5) / (doc_freq + 0.5)))
            numerator = freq * (self.k1 + 1.0)
            denominator = freq + self.k1 * (
                1.0 - self.b + self.b * (doc_len / max(self._avg_doc_len, 1.0))
            )
            score += idf * (numerator / max(denominator, 1e-9))

        return score
