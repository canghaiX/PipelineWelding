from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import faiss
import httpx

from pipeline_welding.rag.hybrid_retrieval import (
    ChunkRecord,
    bm25_rank,
    load_chunks,
    normalize_embeddings,
    reciprocal_rank_fusion,
    tokenize_for_keyword_search,
)


DEFAULT_INDEX_DIR = Path("data/rag/faiss")
DEFAULT_EMBEDDING_URL = "http://127.0.0.1:8001/v1/embeddings"
DEFAULT_RERANK_URL = "http://127.0.0.1:8002/rerank"
DEFAULT_EMBEDDING_MODEL = "bge-m3"
DEFAULT_RERANK_MODEL = "bge-reranker-v2-m3"


@dataclass(frozen=True)
class HybridRagConfig:
    enabled: bool = True
    index_dir: Path = DEFAULT_INDEX_DIR
    embedding_url: str = DEFAULT_EMBEDDING_URL
    rerank_url: str = DEFAULT_RERANK_URL
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    rerank_model: str = DEFAULT_RERANK_MODEL
    semantic_top_k: int = 10
    keyword_top_k: int = 10
    fusion_top_k: int = 10
    final_top_k: int = 5
    rrf_k: int = 60


def chunk_text_for_retrieval(chunk: ChunkRecord) -> str:
    parts = [
        chunk.source_file.strip(),
        f"页码: {chunk.page_start}-{chunk.page_end}" if chunk.page_start and chunk.page_end else "",
        chunk.section_title.strip(),
        chunk.text.strip(),
    ]
    return "\n\n".join(part for part in parts if part)


def embed_query(query: str, embedding_url: str, model_name: str) -> Any:
    with httpx.Client(timeout=60.0) as client:
        response = client.post(embedding_url, json={"model": model_name, "input": [query]})
        response.raise_for_status()
        embedding = response.json()["data"][0]["embedding"]
    return normalize_embeddings([embedding])


def semantic_rank(index: faiss.Index, query: str, embedding_url: str, model_name: str, top_k: int) -> list[tuple[int, float]]:
    query_vector = embed_query(query, embedding_url, model_name)
    scores, indices = index.search(query_vector, top_k)
    ranked: list[tuple[int, float]] = []
    for index_id, score in zip(indices[0].tolist(), scores[0].tolist(), strict=False):
        if index_id >= 0:
            ranked.append((int(index_id), float(score)))
    return ranked


def parse_rerank_payload(payload: dict[str, Any], candidate_ids: list[int], chunks: list[ChunkRecord]) -> list[dict[str, Any]]:
    raw_results = payload.get("results") or payload.get("data") or []
    parsed: list[dict[str, Any]] = []
    for rank, item in enumerate(raw_results):
        if not isinstance(item, dict):
            continue
        local_index = int(item.get("index", item.get("document_index", rank)))
        if local_index < 0 or local_index >= len(candidate_ids):
            continue
        chunk_index = candidate_ids[local_index]
        score = item.get("relevance_score", item.get("score", item.get("logit", 0.0)))
        parsed.append({"score": float(score), "chunk": chunks[chunk_index].to_json()})
    return parsed


def rerank(
    query: str,
    chunks: list[ChunkRecord],
    candidate_ids: list[int],
    rerank_url: str,
    model_name: str,
    top_k: int,
) -> list[dict[str, Any]]:
    documents = [chunk_text_for_retrieval(chunks[index]) for index in candidate_ids]
    with httpx.Client(timeout=120.0) as client:
        response = client.post(
            rerank_url,
            json={"model": model_name, "query": query, "documents": documents, "top_n": top_k},
        )
        if response.status_code == 404 and rerank_url.rstrip("/").endswith("/rerank"):
            fallback = rerank_url.rstrip("/").removesuffix("/rerank") + "/v1/rerank"
            response = client.post(
                fallback,
                json={"model": model_name, "query": query, "documents": documents, "top_n": top_k},
            )
        response.raise_for_status()
        payload = response.json()

    return parse_rerank_payload(payload, candidate_ids, chunks)[:top_k]


def hybrid_search(
    query: str,
    index_dir: Path,
    embedding_url: str,
    rerank_url: str,
    embedding_model: str,
    rerank_model: str,
    semantic_top_k: int,
    keyword_top_k: int,
    fusion_top_k: int,
    final_top_k: int,
    rrf_k: int = 60,
) -> dict[str, Any]:
    index = faiss.read_index(str(index_dir / "docs.faiss"))
    chunks = load_chunks(index_dir / "chunks.jsonl")
    corpus_tokens = [tokenize_for_keyword_search(chunk_text_for_retrieval(chunk)) for chunk in chunks]

    semantic = semantic_rank(index, query, embedding_url, embedding_model, semantic_top_k)
    keyword = bm25_rank(query, corpus_tokens, keyword_top_k)
    fused = reciprocal_rank_fusion(
        [[index for index, _ in semantic], [index for index, _ in keyword]],
        top_k=fusion_top_k,
        rrf_k=rrf_k,
    )
    candidate_ids = [index for index, _ in fused]
    final = rerank(query, chunks, candidate_ids, rerank_url, rerank_model, final_top_k) if candidate_ids else []

    return {
        "query": query,
        "semantic_top_k": semantic_top_k,
        "keyword_top_k": keyword_top_k,
        "fusion_top_k": fusion_top_k,
        "final_top_k": final_top_k,
        "rrf_k": rrf_k,
        "semantic_candidates": [{"index": index, "score": score, "chunk_id": chunks[index].chunk_id} for index, score in semantic],
        "keyword_candidates": [{"index": index, "score": score, "chunk_id": chunks[index].chunk_id} for index, score in keyword],
        "fused_candidates": [{"index": index, "score": score, "chunk_id": chunks[index].chunk_id} for index, score in fused],
        "results": final,
    }


class HybridRagRetriever:
    def __init__(self, config: HybridRagConfig | None = None) -> None:
        self.config = config or HybridRagConfig()

    def search(self, query: str) -> dict[str, Any]:
        if not self.config.enabled:
            return {"query": query, "results": []}
        return hybrid_search(
            query=query,
            index_dir=self.config.index_dir,
            embedding_url=self.config.embedding_url,
            rerank_url=self.config.rerank_url,
            embedding_model=self.config.embedding_model,
            rerank_model=self.config.rerank_model,
            semantic_top_k=self.config.semantic_top_k,
            keyword_top_k=self.config.keyword_top_k,
            fusion_top_k=self.config.fusion_top_k,
            final_top_k=self.config.final_top_k,
            rrf_k=self.config.rrf_k,
        )
