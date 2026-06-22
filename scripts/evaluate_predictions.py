#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pipeline_welding.evaluation import aggregate_numeric_metrics, evaluate_sample


def load_records(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("results", "samples", "records", "data"):
            if isinstance(payload.get(key), list):
                return payload[key]
    raise ValueError(f"Unsupported prediction file shape: {path}")


def pick(record: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return default


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate PipelineWelding RAG/agent prediction records.")
    parser.add_argument("input", type=Path, help="JSON or JSONL records with prediction/gold/retrieval payload.")
    parser.add_argument("--output", type=Path, default=Path("result/eval_metrics.json"))
    args = parser.parse_args()

    records = load_records(args.input)
    evaluated: list[dict[str, Any]] = []

    for index, record in enumerate(records):
        prediction = pick(record, "prediction", "pred", "answer", "output")
        gold = pick(record, "gold", "gold_answer", "reference", "target")
        retrieval_payload = pick(record, "retrieval_payload", "rag_payload", "rag_result", "retrieval", default={})
        sample = dict(record)
        metrics = evaluate_sample(
            prediction=str(prediction),
            gold=str(gold),
            sample=sample,
            retrieval_payload=retrieval_payload,
            aliases=record.get("answer_aliases"),
            latency=record.get("latency"),
            tool_calls=record.get("tool_calls"),
        )
        evaluated.append({"idx": record.get("idx", index), **record, **metrics})

    summary = {
        "num_samples": len(evaluated),
        "answer_metrics": aggregate_numeric_metrics(evaluated, "answer_metrics"),
        "retrieval_metrics": aggregate_numeric_metrics(evaluated, "retrieval_metrics"),
        "grounding_metrics": aggregate_numeric_metrics(evaluated, "grounding_metrics"),
        "process_metrics": aggregate_numeric_metrics(evaluated, "process_metrics"),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"summary": summary, "results": evaluated}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()
