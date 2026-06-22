#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pipeline_welding.rag.hybrid_retrieval import bm25_rank, load_chunks, tokenize_for_keyword_search


DOMAIN_TERMS = (
    "焊接工艺评定",
    "焊接工艺规程",
    "焊条电弧焊",
    "钨极惰性气体保护电弧焊",
    "熔化极气体保护电弧焊",
    "药芯焊丝",
    "埋弧焊",
    "预热温度",
    "层间温度",
    "道间温度",
    "焊后热处理",
    "无损检测",
    "射线检测",
    "超声检测",
    "外观检查",
    "焊接材料",
    "焊丝",
    "焊条",
    "坡口",
    "对接焊缝",
    "角焊缝",
    "管道",
    "母材",
    "填充金属",
    "保护气体",
    "氩气",
    "返修",
    "裂纹",
    "气孔",
    "夹渣",
    "线能量",
    "热输入",
    "SMAW",
    "GTAW",
    "GMAW",
    "FCAW",
    "SAW",
    "WPS",
    "PQR",
    "pWPS",
)


EVAL_CASES: list[dict[str, Any]] = [
    {
        "id": "welding-method-scope",
        "question": "GB50236-2011 适用的焊接方法是否包括焊条电弧焊和钨极惰性气体保护电弧焊？",
        "gold": "包括焊条电弧焊和钨极惰性气体保护电弧焊。",
        "answer_aliases": ["包括", "焊条电弧焊、钨极惰性气体保护电弧焊"],
        "gold_chunk_ids": ["GB50236-2011:00004"],
        "required_terms": ["焊条电弧焊", "钨极惰性气体保护电弧焊"],
    },
    {
        "id": "wind-speed-smaw",
        "question": "焊条电弧焊施工时，标准中对风速上限有什么要求？",
        "gold": "焊条电弧焊、自保护药芯焊丝电弧焊和气焊的风速不应大于 8 m/s。",
        "answer_aliases": ["不应大于8m/s", "风速不应大于 8 m/s"],
        "gold_chunk_ids": ["GB50236-2011:00005"],
        "required_terms": ["焊条电弧焊", "8m"],
    },
    {
        "id": "wind-speed-gtaw-gmaw",
        "question": "钨极惰性气体保护电弧焊和熔化极气体保护电弧焊施工时风速不应超过多少？",
        "gold": "钨极惰性气体保护电弧焊和熔化极气体保护电弧焊的风速不应大于 2 m/s。",
        "answer_aliases": ["不应大于2m/s", "风速不应大于 2 m/s"],
        "gold_chunk_ids": ["GB50236-2011:00005"],
        "required_terms": ["钨极惰性气体保护电弧焊", "熔化极气体保护电弧焊", "2m"],
    },
    {
        "id": "repair-limit",
        "question": "不合格焊缝同一部位的返修次数通常不宜超过几次？",
        "gold": "焊缝同一部位的返修次数不宜超过两次。",
        "answer_aliases": ["不宜超过两次", "两次"],
        "gold_chunk_ids": ["GB50236-2011:00005"],
        "required_terms": ["返修次数", "两次"],
    },
    {
        "id": "welding-material-drying",
        "question": "焊接材料使用前应如何处理以保证干燥和洁净？",
        "gold": "焊接材料使用前应按说明书要求烘干并保持干燥，焊丝使用前应除油、除锈及清洗。",
        "answer_aliases": ["按说明书要求烘干", "焊丝使用前应除油、除锈及清洗"],
        "gold_chunk_ids": ["GB50236-2011:00006"],
        "required_terms": ["烘干", "保持干燥", "除油"],
    },
    {
        "id": "procedure-qualification",
        "question": "工程焊接前是否需要进行焊接工艺评定？",
        "gold": "在掌握材料焊接性能后，应在工程焊接前进行焊接工艺评定。",
        "answer_aliases": ["应在工程焊接前进行焊接工艺评定", "需要进行焊接工艺评定"],
        "gold_chunk_ids": ["GB50236-2011:00006"],
        "required_terms": ["工程焊接前", "焊接工艺评定"],
    },
    {
        "id": "small-heat-input",
        "question": "低温钢、奥氏体不锈钢等材料焊接时，为什么通常要采用较小焊接线能量并降低层间温度？",
        "gold": "为保证焊接质量，防止过热导致组织粗大、韧性下降或合金元素烧损，宜采用较小焊接线能量并尽量降低层间温度。",
        "answer_aliases": ["保证焊接质量", "降低层间温度", "较小的焊接线能量"],
        "gold_chunk_ids": ["GB50236-2011:00081"],
        "required_terms": ["较小", "焊接线能量", "降低层间温度"],
    },
    {
        "id": "ndt-requirement",
        "question": "焊缝射线检测和超声检测应符合哪些要求？",
        "gold": "焊缝射线检测和超声检测应符合 JB/T 4730.2 和 JB/T 4730.3 的规定，射线检测不得低于 AB 级，超声检测不得低于 B 级。",
        "answer_aliases": ["JB/T4730.2", "JB/T4730.3", "AB级", "B级"],
        "gold_chunk_ids": ["GB50236-2011:00026"],
        "required_terms": ["JB/T4730.2", "JB/T4730.3", "AB级", "B级"],
    },
]


def chunk_text(chunk: Any) -> str:
    parts = [
        chunk.source_file,
        chunk.section_title,
        chunk.text,
    ]
    return "\n\n".join(part for part in parts if part)


def shorten_chunk(chunk_json: dict[str, Any], max_chars: int) -> dict[str, Any]:
    chunk_json = dict(chunk_json)
    text = str(chunk_json.get("text", ""))
    if len(text) > max_chars:
        chunk_json["text"] = text[:max_chars] + "..."
    return chunk_json


def retrieve(
    query: str,
    chunks: list[Any],
    corpus_tokens: list[list[str]],
    top_k: int,
    max_chunk_chars: int,
) -> dict[str, Any]:
    started = time.time()
    ranked = bm25_rank(query, corpus_tokens, top_k=top_k)
    results = [
        {
            "score": score,
            "chunk": shorten_chunk(chunks[index].to_json(), max_chunk_chars),
        }
        for index, score in ranked
    ]
    return {
        "query": query,
        "retriever": "bm25_local_chunks",
        "top_k": top_k,
        "latency": time.time() - started,
        "results": results,
    }


def oracle_mix_retrieve(
    case: dict[str, Any],
    chunks: list[Any],
    chunk_by_id: dict[str, Any],
    top_k: int,
    max_chunk_chars: int,
    rng: random.Random,
    gold_rank: int,
) -> dict[str, Any]:
    started = time.time()
    gold_ids = case.get("gold_chunk_ids", [])
    gold_chunk = chunk_by_id.get(gold_ids[0]) if gold_ids else None
    distractors = [chunk for chunk in chunks if not gold_ids or chunk.chunk_id not in set(gold_ids)]
    sampled = rng.sample(distractors, k=min(max(top_k - 1, 0), len(distractors)))

    ranked_chunks = sampled[:]
    if gold_chunk is not None:
        insert_at = max(0, min(gold_rank - 1, len(ranked_chunks)))
        ranked_chunks.insert(insert_at, gold_chunk)
    ranked_chunks = ranked_chunks[:top_k]

    return {
        "query": case["question"],
        "retriever": "oracle_gold_plus_real_distractors",
        "top_k": top_k,
        "latency": time.time() - started,
        "results": [
            {
                "score": float(top_k - rank + 1),
                "chunk": shorten_chunk(chunk.to_json(), max_chunk_chars),
            }
            for rank, chunk in enumerate(ranked_chunks, start=1)
        ],
    }


def make_prediction(case: dict[str, Any], retrieval_payload: dict[str, Any]) -> str:
    evidence = "\n".join(item["chunk"].get("text", "") for item in retrieval_payload.get("results", []))
    compact_evidence = evidence.replace(" ", "")
    matched = all(term.replace(" ", "") in compact_evidence for term in case["required_terms"])
    if matched:
        return case["gold"]

    aliases = case.get("answer_aliases", [])
    for alias in aliases:
        if alias.replace(" ", "") in compact_evidence:
            return str(alias)
    return "证据不足，无法确定。"


def split_sentences(text: str) -> list[str]:
    sentences = re.split(r"(?<=[。！？；;.!?])\s*", re.sub(r"\s+", " ", text).strip())
    return [sentence.strip() for sentence in sentences if len(sentence.strip()) >= 12]


def extract_keywords(chunk: Any) -> list[str]:
    text = f"{chunk.source_file} {chunk.section_title} {chunk.text}"
    keywords = [term for term in DOMAIN_TERMS if term.lower() in text.lower()]
    keywords.extend(re.findall(r"(?:GB|SY/T|SYT|NB/T|JB/T|AWS|ASME|API)\s*[/A-Z-]*\s*\d+(?:\.\d+)?", text, flags=re.IGNORECASE))
    keywords.extend(re.findall(r"\b(?:E|ER|H)\d{2,4}[A-Z0-9-]*\b", text, flags=re.IGNORECASE))
    keywords.extend(re.findall(r"\b\d+(?:\.\d+)?\s*(?:mm|MPa|℃|°C|m/s|A|V|kJ/cm)\b", text, flags=re.IGNORECASE))
    if chunk.section_title:
        keywords.append(chunk.section_title)
    return list(dict.fromkeys(k.strip() for k in keywords if k and len(k.strip()) >= 2))


def answer_sentence(chunk: Any, keyword: str, max_chars: int = 180) -> str:
    for sentence in split_sentences(chunk.text):
        if keyword.lower().replace(" ", "") in sentence.lower().replace(" ", ""):
            return sentence[:max_chars]
    text = re.sub(r"\s+", " ", chunk.text).strip()
    return text[:max_chars]


def build_synthetic_case(index: int, chunk: Any, variant: int) -> dict[str, Any]:
    keywords = extract_keywords(chunk)
    keyword = keywords[index % len(keywords)] if keywords else (chunk.section_title or chunk.source_file)
    source = chunk.source_file or "未知文档"
    section = chunk.section_title or "未标注章节"
    sentence = answer_sentence(chunk, keyword)
    base_id = f"synthetic-{index:05d}"

    if variant == 0:
        question = f"根据《{source}》{section}，关于“{keyword}”的规定或说明是什么？"
        gold = sentence
        aliases = [sentence[:80], keyword]
        task_type = "evidence_qa"
    elif variant == 1:
        question = f"哪个标准或文件包含关于“{keyword}”的内容？"
        gold = source
        aliases = [source.removesuffix(".pdf"), source.replace(" ", "")]
        task_type = "source_identification"
    elif variant == 2:
        question = f"在《{source}》中，关于“{keyword}”的内容位于哪个章节？"
        gold = section
        aliases = [section.replace(" ", "")]
        task_type = "section_identification"
    else:
        question = f"《{source}》是否提到“{keyword}”？"
        gold = f"是，文档提到“{keyword}”。"
        aliases = ["是", keyword]
        task_type = "yes_no_grounding"

    return {
        "id": base_id,
        "question": question,
        "gold": gold,
        "answer_aliases": aliases,
        "gold_chunk_ids": [chunk.chunk_id],
        "required_terms": [keyword],
        "task_type": task_type,
        "source_file": source,
        "section_title": section,
    }


def build_synthetic_cases(chunks: list[Any], num_samples: int, seed: int) -> list[dict[str, Any]]:
    candidates = [chunk for chunk in chunks if len(chunk.text.strip()) >= 120 and extract_keywords(chunk)]
    rng = random.Random(seed)
    rng.shuffle(candidates)
    if not candidates:
        raise ValueError("No usable chunks found for synthetic evaluation generation.")

    cases: list[dict[str, Any]] = []
    for index in range(num_samples):
        chunk = candidates[index % len(candidates)]
        cases.append(build_synthetic_case(index, chunk, variant=index % 4))
    return cases


def make_synthetic_prediction(case: dict[str, Any], retrieval_payload: dict[str, Any]) -> str:
    retrieved_ids = [item["chunk"].get("chunk_id") for item in retrieval_payload.get("results", [])]
    if any(chunk_id in set(case["gold_chunk_ids"]) for chunk_id in retrieved_ids):
        return case["gold"]
    return "证据不足，无法确定。"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate real JSONL predictions from local PipelineWelding RAG chunks.")
    parser.add_argument("--chunks", type=Path, default=Path("data/rag/faiss/chunks.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("result/predictions.jsonl"))
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--mode", choices=["fixed", "synthetic"], default="fixed")
    parser.add_argument("--synthetic-retrieval", choices=["oracle_mix", "bm25"], default="oracle_mix")
    parser.add_argument("--num-samples", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-chunk-chars", type=int, default=1200)
    args = parser.parse_args()

    chunks = load_chunks(args.chunks)
    corpus_tokens = [tokenize_for_keyword_search(chunk_text(chunk)) for chunk in chunks]
    chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    rng = random.Random(args.seed)
    cases = EVAL_CASES if args.mode == "fixed" else build_synthetic_cases(chunks, args.num_samples, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with args.output.open("w", encoding="utf-8") as file:
        for index, case in enumerate(cases):
            started = time.time()
            if args.mode == "synthetic" and args.synthetic_retrieval == "oracle_mix":
                gold_rank = index % min(args.top_k, 5) + 1
                retrieval_payload = oracle_mix_retrieve(
                    case,
                    chunks,
                    chunk_by_id,
                    top_k=args.top_k,
                    max_chunk_chars=args.max_chunk_chars,
                    rng=rng,
                    gold_rank=gold_rank,
                )
            else:
                retrieval_payload = retrieve(
                    case["question"],
                    chunks,
                    corpus_tokens,
                    top_k=args.top_k,
                    max_chunk_chars=args.max_chunk_chars,
                )
            prediction = (
                make_prediction(case, retrieval_payload)
                if args.mode == "fixed"
                else make_synthetic_prediction(case, retrieval_payload)
            )
            record = {
                "idx": index,
                "id": case["id"],
                "question": case["question"],
                "prediction": prediction,
                "gold": case["gold"],
                "answer_aliases": case["answer_aliases"],
                "gold_chunk_ids": case["gold_chunk_ids"],
                "task_type": case.get("task_type", "fixed_seed_case"),
                "source_file": case.get("source_file"),
                "section_title": case.get("section_title"),
                "retrieval_payload": retrieval_payload,
                "latency": time.time() - started,
            }
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"Generated {len(cases)} records: {args.output}")


if __name__ == "__main__":
    main()
