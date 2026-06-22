#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
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


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "num_samples": len(records),
        "answer_metrics": aggregate_numeric_metrics(records, "answer_metrics"),
        "retrieval_metrics": aggregate_numeric_metrics(records, "retrieval_metrics"),
        "grounding_metrics": aggregate_numeric_metrics(records, "grounding_metrics"),
        "process_metrics": aggregate_numeric_metrics(records, "process_metrics"),
    }


def grouped_summary(records: list[dict[str, Any]], key: str = "task_type") -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[str(record.get(key) or "unknown")].append(record)
    return {name: summarize(items) for name, items in sorted(groups.items())}


def metric_value(summary: dict[str, Any], group: str, name: str) -> Any:
    return summary.get(group, {}).get(name, "")


def fmt(value: Any) -> str:
    if value == "" or value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def markdown_report(input_path: Path, output_path: Path, summary: dict[str, Any], by_task_type: dict[str, Any]) -> str:
    retriever = "-"
    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        first = payload.get("results", [{}])[0]
        retriever = first.get("retrieval_payload", {}).get("retriever", "-")
    except Exception:
        pass

    lines = [
        "# PipelineWelding 评测结果汇总",
        "",
        "## 基本信息",
        "",
        "| 项目 | 值 |",
        "| --- | ---: |",
        f"| 预测文件 | `{input_path}` |",
        f"| 评测文件 | `{output_path}` |",
        f"| 样本总数 | {summary['num_samples']} |",
        f"| 检索设置 | `{retriever}` |",
        "",
        "## 整体指标",
        "",
        "| 指标组 | 指标 | 结果 |",
        "| --- | --- | ---: |",
        f"| 答案正确性 | EM | {fmt(metric_value(summary, 'answer_metrics', 'avg_em'))} |",
        f"| 答案正确性 | F1 | {fmt(metric_value(summary, 'answer_metrics', 'avg_f1'))} |",
        f"| 检索质量 | Recall | {fmt(metric_value(summary, 'retrieval_metrics', 'avg_retrieval_recall'))} |",
        f"| 检索质量 | Precision | {fmt(metric_value(summary, 'retrieval_metrics', 'avg_retrieval_precision'))} |",
        f"| 检索质量 | MRR | {fmt(metric_value(summary, 'retrieval_metrics', 'avg_retrieval_mrr'))} |",
        f"| 检索质量 | nDCG | {fmt(metric_value(summary, 'retrieval_metrics', 'avg_retrieval_ndcg'))} |",
        f"| Top-k | Recall@1 | {fmt(metric_value(summary, 'retrieval_metrics', 'avg_retrieval_recall@1'))} |",
        f"| Top-k | Recall@3 | {fmt(metric_value(summary, 'retrieval_metrics', 'avg_retrieval_recall@3'))} |",
        f"| Top-k | Recall@5 | {fmt(metric_value(summary, 'retrieval_metrics', 'avg_retrieval_recall@5'))} |",
        f"| 证据支撑 | Groundedness | {fmt(metric_value(summary, 'grounding_metrics', 'avg_groundedness'))} |",
        f"| 过程效率 | Retrieval Rounds | {fmt(metric_value(summary, 'process_metrics', 'avg_retrieval_rounds'))} |",
        f"| 过程效率 | Retrieved Count | {fmt(metric_value(summary, 'process_metrics', 'avg_retrieved_count'))} |",
        "",
        "## 按任务类型分组",
        "",
        "| 任务类型 | 数量 | EM | F1 | Recall@1 | Recall@3 | Recall@5 | MRR | nDCG | Groundedness |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for task_type, task_summary in by_task_type.items():
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{task_type}`",
                    str(task_summary["num_samples"]),
                    fmt(metric_value(task_summary, "answer_metrics", "avg_em")),
                    fmt(metric_value(task_summary, "answer_metrics", "avg_f1")),
                    fmt(metric_value(task_summary, "retrieval_metrics", "avg_retrieval_recall@1")),
                    fmt(metric_value(task_summary, "retrieval_metrics", "avg_retrieval_recall@3")),
                    fmt(metric_value(task_summary, "retrieval_metrics", "avg_retrieval_recall@5")),
                    fmt(metric_value(task_summary, "retrieval_metrics", "avg_retrieval_mrr")),
                    fmt(metric_value(task_summary, "retrieval_metrics", "avg_retrieval_ndcg")),
                    fmt(metric_value(task_summary, "grounding_metrics", "avg_groundedness")),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- Oracle 版本用于验证数据格式、评测链路和排序上限，不代表真实检索系统效果。",
            "- BM25 版本用于真实关键词检索 baseline，更适合作为后续 Hybrid RAG、reranker 和 Agentic RAG 的对照。",
            "- `groundedness` 是启发式 token 覆盖率，不等价于 LLM-as-judge faithfulness。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate PipelineWelding RAG/agent prediction records.")
    parser.add_argument("input", type=Path, help="JSON or JSONL records with prediction/gold/retrieval payload.")
    parser.add_argument("--output", type=Path, default=Path("result/eval_metrics.json"))
    parser.add_argument("--report", type=Path, default=None, help="Optional Markdown report output path")
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

    summary = summarize(evaluated)
    by_task_type = grouped_summary(evaluated)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps({"summary": summary, "by_task_type": by_task_type, "results": evaluated}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(markdown_report(args.input, args.output, summary, by_task_type), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Saved to {args.output}")
    if args.report:
        print(f"Report saved to {args.report}")


if __name__ == "__main__":
    main()
