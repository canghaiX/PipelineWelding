from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from pipeline_welding.rag.hybrid_retrieval import (
    ChunkRecord,
    bm25_rank,
    load_chunks,
    reciprocal_rank_fusion,
    tokenize_for_keyword_search,
)


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "rag_search.py"
SPEC = importlib.util.spec_from_file_location("rag_search", SCRIPT_PATH)
assert SPEC and SPEC.loader
rag_search = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = rag_search
SPEC.loader.exec_module(rag_search)


def test_tokenizer_keeps_domain_terms_for_keyword_recall() -> None:
    tokens = tokenize_for_keyword_search("GB/T 31032 和 ER50-6 焊丝适用于 P-No.1 管道")

    assert "gb/t" in tokens
    assert "31032" in tokens
    assert "gb/t31032" in tokens
    assert "er50-6" in tokens
    assert "p-no.1" in tokens


def test_bm25_ranks_matching_standard_above_unrelated_text() -> None:
    corpus = [
        tokenize_for_keyword_search("焊缝外观检查和返修要求"),
        tokenize_for_keyword_search("GB/T 31032 管道焊接工艺评定要求"),
    ]

    ranked = bm25_rank("GB/T 31032 工艺评定", corpus, top_k=2)

    assert ranked[0][0] == 1
    assert ranked[0][1] > 0


def test_rrf_fuses_semantic_and_keyword_rankings() -> None:
    fused = reciprocal_rank_fusion([[2, 1, 0], [1, 3, 2]], top_k=3, rrf_k=60)

    assert [index for index, _ in fused] == [1, 2, 3]


def test_load_chunks_preserves_required_source_fields(tmp_path: Path) -> None:
    path = tmp_path / "chunks.jsonl"
    path.write_text(
        json.dumps(
            {
                "chunk_id": "sample-0001",
                "source_file": "GB50236-2011.pdf",
                "source_path": "docs/GB50236-2011.pdf",
                "page_start": 3,
                "page_end": 4,
                "chunk_type": "table",
                "section_title": "焊接材料",
                "text": "表头: 牌号 | 规格",
                "metadata": {"table_header": ["牌号", "规格"], "pages": [3, 4]},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    [chunk] = load_chunks(path)

    assert chunk.chunk_id == "sample-0001"
    assert chunk.source_file == "GB50236-2011.pdf"
    assert chunk.page_start == 3
    assert chunk.page_end == 4
    assert chunk.metadata["table_header"] == ["牌号", "规格"]


def test_parse_rerank_payload_accepts_results_and_data_shapes() -> None:
    chunks = [
        ChunkRecord(chunk_id="a", text="第一条", metadata={}),
        ChunkRecord(chunk_id="b", text="第二条", metadata={}),
    ]

    results_shape = rag_search.parse_rerank_payload(
        {"results": [{"index": 1, "relevance_score": 0.9}]},
        [0, 1],
        chunks,
    )
    data_shape = rag_search.parse_rerank_payload(
        {"data": [{"document_index": 0, "score": 0.8}]},
        [0, 1],
        chunks,
    )

    assert results_shape[0]["chunk"]["chunk_id"] == "b"
    assert results_shape[0]["score"] == 0.9
    assert data_shape[0]["chunk"]["chunk_id"] == "a"
    assert data_shape[0]["score"] == 0.8
