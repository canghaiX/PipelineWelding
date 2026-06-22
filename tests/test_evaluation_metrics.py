from __future__ import annotations

from pipeline_welding.evaluation import (
    aggregate_numeric_metrics,
    answer_correctness,
    build_evidence_text,
    evaluate_sample,
    extract_retrieved_chunk_ids,
    retrieval_quality_with_topk,
)


def test_answer_correctness_uses_aliases() -> None:
    metrics = answer_correctness("GTAW+SMAW", "钨极氩弧焊打底+焊条电弧焊填充", ["GTAW+SMAW"])

    assert metrics["em"] == 1.0
    assert metrics["f1"] == 1.0


def test_extract_retrieved_chunk_ids_from_pipeline_welding_payload() -> None:
    payload = {
        "results": [
            {
                "score": 0.91,
                "chunk": {
                    "chunk_id": "gb50236-001",
                    "source_file": "GB50236-2011.pdf",
                    "text": "预热温度和层间温度应符合焊接工艺规程。",
                },
            }
        ],
        "semantic_candidates": [{"chunk_id": "gb50236-001"}, {"chunk_id": "syt4109-002"}],
    }

    assert extract_retrieved_chunk_ids(payload) == ["gb50236-001", "syt4109-002"]
    assert "[gb50236-001]" in build_evidence_text(payload)


def test_retrieval_quality_reports_topk_mrr_and_ndcg() -> None:
    metrics = retrieval_quality_with_topk(["a", "b", "c"], {"b", "d"})

    assert metrics["retrieval_hit"] == 1.0
    assert metrics["retrieval_recall"] == 0.5
    assert metrics["retrieval_precision"] == 1 / 3
    assert metrics["retrieval_mrr"] == 0.5
    assert metrics["retrieval_recall@1"] == 0.0
    assert metrics["retrieval_recall@3"] == 0.5
    assert 0.0 < metrics["retrieval_ndcg"] < 1.0


def test_evaluate_sample_returns_paper_ready_metric_groups() -> None:
    sample = {
        "gold_chunk_ids": ["gb50236-001"],
        "answer_aliases": ["GTAW+SMAW"],
    }
    retrieval_payload = {
        "results": [
            {
                "score": 0.9,
                "chunk": {
                    "chunk_id": "gb50236-001",
                    "source_file": "GB50236-2011.pdf",
                    "text": "GTAW+SMAW 可用于管道焊接工艺。",
                },
            }
        ]
    }

    result = evaluate_sample(
        prediction="GTAW+SMAW",
        gold="钨极氩弧焊打底+焊条电弧焊填充",
        sample=sample,
        retrieval_payload=retrieval_payload,
        latency=0.2,
    )

    assert result["answer_metrics"]["em"] == 1.0
    assert result["retrieval_metrics"]["retrieval_recall"] == 1.0
    assert result["grounding_metrics"]["groundedness"] == 1.0
    assert result["process_metrics"]["latency"] == 0.2

    summary = aggregate_numeric_metrics([result], "retrieval_metrics")
    assert summary["avg_retrieval_recall"] == 1.0
