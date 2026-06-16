#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pipeline_welding.rag.retriever import (
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_EMBEDDING_URL,
    DEFAULT_INDEX_DIR,
    DEFAULT_RERANK_MODEL,
    DEFAULT_RERANK_URL,
    hybrid_search,
    parse_rerank_payload,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hybrid RAG search: BGE-M3 + BM25 + RRF + BGE reranker.")
    parser.add_argument("query", type=str)
    parser.add_argument("--index-dir", type=Path, default=DEFAULT_INDEX_DIR)
    parser.add_argument("--embedding-url", type=str, default=DEFAULT_EMBEDDING_URL)
    parser.add_argument("--rerank-url", type=str, default=DEFAULT_RERANK_URL)
    parser.add_argument("--embedding-model", type=str, default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--rerank-model", type=str, default=DEFAULT_RERANK_MODEL)
    parser.add_argument("--semantic-top-k", type=int, default=10)
    parser.add_argument("--keyword-top-k", type=int, default=10)
    parser.add_argument("--fusion-top-k", type=int, default=10)
    parser.add_argument("--final-top-k", type=int, default=5)
    parser.add_argument("--rrf-k", type=int, default=60)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = hybrid_search(
        query=args.query,
        index_dir=args.index_dir,
        embedding_url=args.embedding_url,
        rerank_url=args.rerank_url,
        embedding_model=args.embedding_model,
        rerank_model=args.rerank_model,
        semantic_top_k=args.semantic_top_k,
        keyword_top_k=args.keyword_top_k,
        fusion_top_k=args.fusion_top_k,
        final_top_k=args.final_top_k,
        rrf_k=args.rrf_k,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
