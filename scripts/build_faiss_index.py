#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import faiss
import httpx
import numpy as np

from pipeline_welding.rag.hybrid_retrieval import ChunkRecord, load_chunks, normalize_embeddings


DEFAULT_CHUNKS_PATH = Path("data/rag/pdf_chunks.jsonl")
DEFAULT_OUTPUT_DIR = Path("data/rag/faiss")
DEFAULT_EMBEDDING_URL = "http://127.0.0.1:8001/v1/embeddings"
DEFAULT_MODEL_NAME = "bge-m3"


@dataclass(frozen=True)
class IndexManifest:
    chunks_path: str
    index_path: str
    chunks_meta_path: str
    embedding_url: str
    model_name: str
    vector_count: int
    vector_dim: int


def chunk_text(record: ChunkRecord) -> str:
    parts = [record.section_title.strip(), record.text.strip()]
    return "\n\n".join(part for part in parts if part)


def embed_texts(texts: list[str], embedding_url: str, model_name: str, batch_size: int = 32) -> np.ndarray:
    vectors: list[list[float]] = []
    with httpx.Client(timeout=120.0) as client:
        for offset in range(0, len(texts), batch_size):
            batch = texts[offset : offset + batch_size]
            response = client.post(
                embedding_url,
                json={"model": model_name, "input": batch},
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data", [])
            if not isinstance(data, list):
                raise ValueError("Unexpected embeddings response format")
            vectors.extend(item["embedding"] for item in data)
    return normalize_embeddings(vectors)


def build_index(
    chunks: list[ChunkRecord],
    embedding_url: str,
    model_name: str,
    batch_size: int,
) -> tuple[faiss.Index, np.ndarray]:
    texts = [chunk_text(chunk) for chunk in chunks]
    embeddings = embed_texts(texts, embedding_url=embedding_url, model_name=model_name, batch_size=batch_size)
    if embeddings.size == 0:
        raise ValueError("No embeddings were generated")

    dimension = embeddings.shape[1]
    index = faiss.IndexFlatIP(dimension)
    index.add(embeddings.astype("float32"))
    return index, embeddings


def write_outputs(
    output_dir: Path,
    index: faiss.Index,
    chunks: list[ChunkRecord],
    embedding_url: str,
    model_name: str,
    chunks_path: Path,
) -> IndexManifest:
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = output_dir / "docs.faiss"
    chunks_meta_path = output_dir / "chunks.jsonl"
    manifest_path = output_dir / "manifest.json"

    faiss.write_index(index, str(index_path))
    with chunks_meta_path.open("w", encoding="utf-8") as file:
        for chunk in chunks:
            file.write(json.dumps(chunk.to_json(), ensure_ascii=False) + "\n")

    manifest = IndexManifest(
        chunks_path=str(chunks_path),
        index_path=str(index_path),
        chunks_meta_path=str(chunks_meta_path),
        embedding_url=embedding_url,
        model_name=model_name,
        vector_count=len(chunks),
        vector_dim=index.d,
    )
    manifest_path.write_text(json.dumps(asdict(manifest), ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a FAISS index from MinerU RAG chunks.")
    parser.add_argument("--chunks-path", type=Path, default=DEFAULT_CHUNKS_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--embedding-url", type=str, default=DEFAULT_EMBEDDING_URL)
    parser.add_argument("--model-name", type=str, default=DEFAULT_MODEL_NAME)
    parser.add_argument("--batch-size", type=int, default=32)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    chunks = load_chunks(args.chunks_path)
    index, _ = build_index(
        chunks,
        embedding_url=args.embedding_url,
        model_name=args.model_name,
        batch_size=args.batch_size,
    )
    manifest = write_outputs(args.output_dir, index, chunks, args.embedding_url, args.model_name, args.chunks_path)
    print(json.dumps(asdict(manifest), ensure_ascii=False))


if __name__ == "__main__":
    main()
