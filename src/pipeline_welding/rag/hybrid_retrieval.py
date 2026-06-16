from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


TOKEN_RE = re.compile(r"[A-Za-z0-9_+#./-]+|[\u4e00-\u9fff]")


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    text: str
    metadata: dict[str, Any]
    source_file: str = ""
    source_path: str = ""
    page_start: int = 0
    page_end: int = 0
    chunk_type: str = ""
    section_title: str = ""

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "ChunkRecord":
        return cls(
            chunk_id=str(payload.get("chunk_id", "")),
            text=str(payload.get("text", "")),
            metadata=dict(payload.get("metadata", {})),
            source_file=str(payload.get("source_file", "")),
            source_path=str(payload.get("source_path", "")),
            page_start=int(payload.get("page_start", 0) or 0),
            page_end=int(payload.get("page_end", 0) or 0),
            chunk_type=str(payload.get("chunk_type", "")),
            section_title=str(payload.get("section_title", "")),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "source_file": self.source_file,
            "source_path": self.source_path,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "chunk_type": self.chunk_type,
            "section_title": self.section_title,
            "text": self.text,
            "metadata": self.metadata,
        }


def load_chunks(path: Path) -> list[ChunkRecord]:
    chunks: list[ChunkRecord] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                chunks.append(ChunkRecord.from_json(json.loads(line)))
    return chunks


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_embeddings(values: list[list[float]] | np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype="float32")
    if array.ndim == 1:
        array = array.reshape(1, -1)
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return array / norms


def tokenize_for_keyword_search(text: str) -> list[str]:
    tokens = [match.group(0).lower() for match in TOKEN_RE.finditer(text)]
    merged_terms = extract_domain_terms(text)
    return tokens + merged_terms


def extract_domain_terms(text: str) -> list[str]:
    compact = text.lower()
    terms: list[str] = []
    for pattern in (
        r"gb/?t\s*\d+(?:\.\d+)?",
        r"gb\s*\d+(?:\.\d+)?",
        r"sy/?t\s*\d+(?:\.\d+)?",
        r"nb/?t\s*\d+(?:\.\d+)?",
        r"aws\s*a\d+(?:\.\d+)?",
        r"asme\s*[a-z0-9. -]+",
        r"e\d{4}[a-z0-9-]*",
        r"er\d{2}s-?\d",
        r"p-no\.?\s*\d+",
    ):
        terms.extend(re.sub(r"\s+", "", match.group(0)) for match in re.finditer(pattern, compact))
    return terms


def bm25_rank(
    query: str,
    corpus_tokens: list[list[str]],
    top_k: int,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[tuple[int, float]]:
    query_tokens = tokenize_for_keyword_search(query)
    if not query_tokens or not corpus_tokens:
        return []

    doc_count = len(corpus_tokens)
    avg_doc_len = sum(len(tokens) for tokens in corpus_tokens) / max(doc_count, 1)
    doc_freq: dict[str, int] = {}
    for tokens in corpus_tokens:
        for token in set(tokens):
            doc_freq[token] = doc_freq.get(token, 0) + 1

    scores: list[tuple[int, float]] = []
    for doc_index, tokens in enumerate(corpus_tokens):
        if not tokens:
            continue
        frequencies: dict[str, int] = {}
        for token in tokens:
            frequencies[token] = frequencies.get(token, 0) + 1

        score = 0.0
        doc_len = len(tokens)
        for token in query_tokens:
            freq = frequencies.get(token, 0)
            if freq == 0:
                continue
            df = doc_freq.get(token, 0)
            idf = math.log(1 + (doc_count - df + 0.5) / (df + 0.5))
            denom = freq + k1 * (1 - b + b * doc_len / max(avg_doc_len, 1e-6))
            score += idf * (freq * (k1 + 1) / denom)
        if score > 0:
            scores.append((doc_index, score))

    return sorted(scores, key=lambda item: item[1], reverse=True)[:top_k]


def reciprocal_rank_fusion(
    ranked_lists: list[list[int]],
    top_k: int,
    rrf_k: int = 60,
) -> list[tuple[int, float]]:
    scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, doc_index in enumerate(ranked, start=1):
            scores[doc_index] = scores.get(doc_index, 0.0) + 1.0 / (rrf_k + rank)
    return sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]
