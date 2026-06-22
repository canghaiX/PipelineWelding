from __future__ import annotations

import re
import string
import time
import unicodedata
from collections import Counter
from math import log2
from statistics import mean
from typing import Any


CN_PUNCTUATION = '。，、；：？！""''【】《》（）｛｝〔〕·…—～'
ALL_PUNCTUATION = set(string.punctuation) | set(CN_PUNCTUATION)


def normalize_text(text: str) -> str:
    normalized_chars: list[str] = []
    for char in str(text):
        code = ord(char)
        if 0xFF01 <= code <= 0xFF5E:
            normalized_chars.append(chr(code - 0xFEE0))
        elif char == "\u3000" or unicodedata.category(char).startswith("Zs"):
            normalized_chars.append(" ")
        else:
            normalized_chars.append(char)

    text = "".join(normalized_chars).lower()
    text = "".join(char for char in text if char not in ALL_PUNCTUATION)
    text = re.sub(r"(\d)([\u4e00-\u9fff])", r"\1 \2", text)
    text = re.sub(r"([\u4e00-\u9fff])(\d)", r"\1 \2", text)
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    return " ".join(text.split())


def exact_match(prediction: str, gold: str, aliases: list[str] | None = None) -> float:
    candidates = [gold, *(aliases or [])]
    return max(1.0 if normalize_text(prediction) == normalize_text(candidate) else 0.0 for candidate in candidates)


def token_f1(prediction: str, gold: str) -> float:
    pred_tokens = normalize_text(prediction).split()
    gold_tokens = normalize_text(gold).split()

    if not gold_tokens:
        return 1.0 if not pred_tokens else 0.0
    if not pred_tokens:
        return 0.0

    common = Counter(pred_tokens) & Counter(gold_tokens)
    overlap = sum(common.values())
    if overlap == 0:
        return 0.0

    precision = overlap / len(pred_tokens)
    recall = overlap / len(gold_tokens)
    return 2 * precision * recall / (precision + recall)


def f1_score(prediction: str, gold: str, aliases: list[str] | None = None) -> float:
    candidates = [gold, *(aliases or [])]
    return max(token_f1(prediction, candidate) for candidate in candidates if candidate)


def answer_correctness(prediction: str, gold: str, aliases: list[str] | None = None) -> dict[str, float]:
    return {
        "em": exact_match(prediction, gold, aliases),
        "f1": f1_score(prediction, gold, aliases),
    }


def extract_gold_chunk_ids(sample: dict[str, Any]) -> set[str]:
    gold_ids: set[str] = set()
    for key in ("gold_chunk_ids", "gold_chunks", "evidence_chunk_ids", "reference_chunk_ids"):
        value = sample.get(key, [])
        if isinstance(value, str):
            value = [value]
        for chunk_id in value or []:
            if chunk_id:
                gold_ids.add(str(chunk_id))

    for hop in sample.get("hops", []) or []:
        if isinstance(hop, dict) and hop.get("doc_chunk_id"):
            gold_ids.add(str(hop["doc_chunk_id"]))

    return gold_ids


def extract_retrieved_chunk_ids(payload: Any) -> list[str]:
    ids: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("chunk_id"):
                ids.append(str(value["chunk_id"]))
            chunk = value.get("chunk")
            if isinstance(chunk, dict) and chunk.get("chunk_id"):
                ids.append(str(chunk["chunk_id"]))
            raw = value.get("raw")
            if isinstance(raw, dict):
                visit(raw)
            for key in ("results", "semantic_candidates", "keyword_candidates", "fused_candidates", "rag_evidence"):
                child = value.get(key)
                if child is not None:
                    visit(child)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str):
            ids.extend(match.group(1) for match in re.finditer(r"\[([^\]\s]+)\]", value))

    visit(payload)
    return list(dict.fromkeys(ids))


def retrieval_quality(retrieved_ids: list[str] | set[str], gold_ids: set[str], k: int | None = None) -> dict[str, float | int | None]:
    ordered = list(dict.fromkeys(str(chunk_id) for chunk_id in retrieved_ids if chunk_id))
    if k is not None:
        ordered = ordered[:k]
    retrieved = set(ordered)

    if not gold_ids:
        return {
            "retrieval_hit": None,
            "retrieval_recall": None,
            "retrieval_precision": None,
            "retrieval_f1": None,
            "retrieval_mrr": None,
            "retrieval_ndcg": None,
            "retrieved_count": len(retrieved),
            "gold_count": 0,
            "gold_hit_count": 0,
        }

    hits = retrieved & gold_ids
    recall = len(hits) / len(gold_ids)
    precision = len(hits) / len(retrieved) if retrieved else 0.0
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    first_hit_rank = next((rank for rank, chunk_id in enumerate(ordered, start=1) if chunk_id in gold_ids), None)
    mrr = 1.0 / first_hit_rank if first_hit_rank else 0.0
    dcg = sum(1.0 / log2(rank + 1) for rank, chunk_id in enumerate(ordered, start=1) if chunk_id in gold_ids)
    ideal_hits = min(len(gold_ids), len(ordered))
    idcg = sum(1.0 / log2(rank + 1) for rank in range(1, ideal_hits + 1))

    return {
        "retrieval_hit": 1.0 if hits else 0.0,
        "retrieval_recall": recall,
        "retrieval_precision": precision,
        "retrieval_f1": f1,
        "retrieval_mrr": mrr,
        "retrieval_ndcg": dcg / idcg if idcg else 0.0,
        "retrieved_count": len(retrieved),
        "gold_count": len(gold_ids),
        "gold_hit_count": len(hits),
    }


def retrieval_quality_with_topk(
    retrieved_ids: list[str] | set[str],
    gold_ids: set[str],
    ks: tuple[int, ...] = (1, 3, 5),
) -> dict[str, float | int | None]:
    metrics = retrieval_quality(retrieved_ids, gold_ids)
    for k in ks:
        topk = retrieval_quality(retrieved_ids, gold_ids, k=k)
        for name, value in topk.items():
            if name in {"retrieved_count", "gold_count", "gold_hit_count"}:
                continue
            metrics[f"{name}@{k}"] = value
    return metrics


def build_evidence_text(payload: Any, max_chars_per_chunk: int = 800) -> str:
    parts: list[str] = []
    seen: set[str] = set()

    def add_chunk(chunk: dict[str, Any], score: Any = None) -> None:
        chunk_id = str(chunk.get("chunk_id", ""))
        if chunk_id and chunk_id in seen:
            return
        if chunk_id:
            seen.add(chunk_id)
        title = str(chunk.get("source_file") or chunk.get("section_title") or "")
        text = str(chunk.get("text", ""))[:max_chars_per_chunk]
        prefix = f"[{chunk_id}]" if chunk_id else "[evidence]"
        score_text = f" score={score}" if score is not None else ""
        parts.append(f"{prefix}{score_text} {title}\n{text}".strip())

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            chunk = value.get("chunk")
            if isinstance(chunk, dict):
                add_chunk(chunk, value.get("score"))
            elif value.get("chunk_id") and value.get("text"):
                add_chunk(value, value.get("score"))
            for key in ("results", "rag_evidence"):
                child = value.get(key)
                if child is not None:
                    visit(child)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(payload)
    return "\n\n".join(part for part in parts if part)


def groundedness_score(answer: str, evidence_text: str) -> float:
    if not answer or not evidence_text:
        return 0.0
    answer_tokens = [token for token in normalize_text(answer).split() if len(token) > 1]
    evidence_tokens = set(normalize_text(evidence_text).split())
    if not answer_tokens or not evidence_tokens:
        return 0.0
    covered = sum(1 for token in answer_tokens if token in evidence_tokens)
    return covered / len(answer_tokens)


def process_metrics(
    *,
    tool_calls: list[Any] | None = None,
    retrieval_payload: dict[str, Any] | None = None,
    latency: float | None = None,
    started_at: float | None = None,
    finished_at: float | None = None,
) -> dict[str, float | int]:
    elapsed = latency
    if elapsed is None and started_at is not None:
        elapsed = (finished_at or time.time()) - started_at

    retrieval_rounds = 1 if retrieval_payload and retrieval_payload.get("results") else 0
    metrics: dict[str, float | int] = {
        "total_tool_calls": len(tool_calls or []),
        "retrieval_rounds": retrieval_rounds,
        "retrieved_count": len(extract_retrieved_chunk_ids(retrieval_payload or {})),
    }
    if elapsed is not None:
        metrics["latency"] = elapsed
    return metrics


def evaluate_sample(
    *,
    prediction: str,
    gold: str,
    sample: dict[str, Any],
    retrieval_payload: Any | None = None,
    aliases: list[str] | None = None,
    latency: float | None = None,
    tool_calls: list[Any] | None = None,
) -> dict[str, Any]:
    aliases = aliases if aliases is not None else sample.get("answer_aliases", [])
    if isinstance(aliases, str):
        aliases = [aliases]

    evidence_text = build_evidence_text(retrieval_payload or {})
    retrieved_ids = extract_retrieved_chunk_ids(retrieval_payload or {})
    gold_ids = extract_gold_chunk_ids(sample)

    return {
        "answer_metrics": answer_correctness(prediction, gold, aliases),
        "retrieval_metrics": retrieval_quality_with_topk(retrieved_ids, gold_ids),
        "grounding_metrics": {
            "groundedness": groundedness_score(prediction, evidence_text),
        },
        "process_metrics": process_metrics(
            tool_calls=tool_calls,
            retrieval_payload=retrieval_payload if isinstance(retrieval_payload, dict) else {},
            latency=latency,
        ),
        "evidence_text": evidence_text,
        "retrieved_chunk_ids": retrieved_ids,
        "gold_chunk_ids": sorted(gold_ids),
    }


def aggregate_numeric_metrics(records: list[dict[str, Any]], key: str | None = None) -> dict[str, float]:
    buckets: dict[str, list[float]] = {}
    for record in records:
        metrics = record.get(key, {}) if key else record
        if not isinstance(metrics, dict):
            continue
        for name, value in metrics.items():
            if isinstance(value, bool):
                value = float(value)
            if isinstance(value, (int, float)) and value is not None:
                buckets.setdefault(name, []).append(float(value))
    return {f"avg_{name}": round(mean(values), 3) for name, values in buckets.items() if values}
