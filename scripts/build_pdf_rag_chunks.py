#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


DEFAULT_DOCS_DIR = Path("docs")
DEFAULT_MINERU_DIR = Path("data/mineru")
DEFAULT_OUTPUT_JSONL = Path("data/rag/pdf_chunks.jsonl")
DEFAULT_BY_FILE_DIR = Path("data/rag/by_file")
DEFAULT_MAX_TABLE_ROWS = 40
DEFAULT_CONTEXT_WINDOW = 3
DEFAULT_MAX_TEXT_CHARS = 1800

IGNORED_CONTEXT_TYPES = {
    "page_header",
    "page_footer",
    "page_number",
    "page_aside_text",
    "page_footnote",
    "header",
    "footer",
    "aside_text",
}


@dataclass(frozen=True)
class TableData:
    header: list[str]
    rows: list[list[str]]
    raw_text: str


@dataclass(frozen=True)
class NormalizedItem:
    index: int
    item_type: str
    text: str
    page: int
    section_title: str
    html: str = ""
    caption: list[str] | None = None
    footnote: list[str] | None = None
    image_path: str = ""


class TableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self.header_rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None
        self._cell_tag: str | None = None
        self._in_thead = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "thead":
            self._in_thead = True
        elif tag == "tr":
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = []
            self._cell_tag = tag
        elif tag == "br" and self._current_cell is not None:
            self._current_cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._current_cell is not None and self._current_row is not None:
            cell = normalize_space("".join(self._current_cell))
            self._current_row.append(cell)
            self._current_cell = None
            self._cell_tag = None
        elif tag == "tr" and self._current_row is not None:
            row = [cell for cell in self._current_row]
            if any(row):
                if self._in_thead:
                    self.header_rows.append(row)
                self.rows.append(row)
            self._current_row = None
        elif tag == "thead":
            self._in_thead = False

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)


def normalize_space(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(normalize_space(item) for item in value if normalize_space(item))
    if isinstance(value, dict):
        if "content" in value:
            return normalize_space(value.get("content"))
        if "item_content" in value:
            return normalize_space(value.get("item_content"))
        if "text" in value:
            return normalize_space(value.get("text"))
    return " ".join(str(value or "").split())


def ensure_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [normalize_space(item) for item in value if normalize_space(item)]
    text = normalize_space(value)
    return [text] if text else []


def parse_table_html(html: str) -> TableData:
    parser = TableHTMLParser()
    parser.feed(html or "")
    rows = [row for row in parser.rows if any(normalize_space(cell) for cell in row)]
    header_rows = parser.header_rows or rows[:1]
    header = flatten_rows(header_rows[:1])
    body_rows = rows[len(header_rows) :] if parser.header_rows else rows[1:]
    raw_text = "\n".join(" | ".join(cell for cell in row) for row in rows)
    return TableData(header=header, rows=body_rows, raw_text=raw_text)


def flatten_rows(rows: list[list[str]]) -> list[str]:
    return [cell for row in rows for cell in row if normalize_space(cell)]


def render_table(header: list[str], rows: list[list[str]]) -> str:
    lines: list[str] = []
    if header:
        lines.append(" | ".join(header))
        lines.append(" | ".join("---" for _ in header))
    lines.extend(" | ".join(row) for row in rows)
    return "\n".join(lines)


def split_rows(rows: list[list[str]], max_rows: int) -> list[list[list[str]]]:
    if max_rows <= 0 or len(rows) <= max_rows:
        return [rows]
    return [rows[index : index + max_rows] for index in range(0, len(rows), max_rows)]


def page_from_item(item: dict[str, Any]) -> int:
    page = item.get("page_idx", item.get("page", item.get("page_no", 0)))
    try:
        page_number = int(page)
    except (TypeError, ValueError):
        page_number = 0
    return page_number + 1 if page_number >= 0 else 1


def get_item_type(item: dict[str, Any]) -> str:
    return normalize_space(item.get("type", "")).lower()


def get_text_from_item(item: dict[str, Any]) -> str:
    content = item.get("content")
    item_type = get_item_type(item)
    if isinstance(content, dict):
        for key in (
            "title_content",
            "paragraph_content",
            "page_header_content",
            "page_footer_content",
            "page_number_content",
            "page_aside_text_content",
            "page_footnote_content",
        ):
            if key in content:
                return normalize_space(content[key])
        if "list_items" in content and isinstance(content["list_items"], list):
            return normalize_space(
                " ".join(
                    normalize_space(item.get("item_content", item)) if isinstance(item, dict) else normalize_space(item)
                    for item in content["list_items"]
                )
            )
    if "text" in item:
        return normalize_space(item.get("text"))
    if item_type == "list" and isinstance(item.get("list_items"), list):
        return normalize_space(" ".join(normalize_space(part) for part in item["list_items"]))
    return ""


def get_table_payload(item: dict[str, Any]) -> tuple[str, list[str], list[str], str]:
    content = item.get("content")
    if isinstance(content, dict):
        html = normalize_space(content.get("html"))
        caption = ensure_list(content.get("table_caption"))
        footnote = ensure_list(content.get("table_footnote"))
        image_source = content.get("image_source") or {}
        image_path = normalize_space(image_source.get("path")) if isinstance(image_source, dict) else ""
        return html, caption, footnote, image_path
    html = normalize_space(item.get("table_body"))
    caption = ensure_list(item.get("table_caption"))
    footnote = ensure_list(item.get("table_footnote"))
    image_path = normalize_space(item.get("img_path"))
    return html, caption, footnote, image_path


def normalize_mineru_items(items: list[dict[str, Any]]) -> list[NormalizedItem]:
    normalized: list[NormalizedItem] = []
    section_title = ""
    for index, item in enumerate(items):
        item_type = get_item_type(item)
        page = page_from_item(item)
        text = get_text_from_item(item)
        if item_type == "title" and text:
            section_title = text
        if item_type == "table":
            html, caption, footnote, image_path = get_table_payload(item)
            normalized.append(
                NormalizedItem(
                    index=index,
                    item_type="table",
                    text=text,
                    page=page,
                    section_title=section_title,
                    html=html,
                    caption=caption,
                    footnote=footnote,
                    image_path=image_path,
                )
            )
        elif text:
            normalized.append(
                NormalizedItem(
                    index=index,
                    item_type=item_type or "text",
                    text=text,
                    page=page,
                    section_title=section_title,
                )
            )
    return normalized


def context_before(items: list[NormalizedItem], position: int, window: int) -> list[str]:
    selected: list[str] = []
    for item in reversed(items[:position]):
        if item.item_type in IGNORED_CONTEXT_TYPES or item.item_type == "table":
            continue
        if item.text:
            selected.append(item.text)
        if len(selected) >= window:
            break
    return list(reversed(selected))


def context_after(items: list[NormalizedItem], position: int, window: int) -> list[str]:
    selected: list[str] = []
    for item in items[position + 1 :]:
        if item.item_type in IGNORED_CONTEXT_TYPES or item.item_type == "table":
            continue
        if item.text:
            selected.append(item.text)
        if len(selected) >= window:
            break
    return selected


def build_table_text(
    source_file: str,
    pages: list[int],
    section_title: str,
    caption: list[str],
    header: list[str],
    before: list[str],
    table_text: str,
    after: list[str],
    footnote: list[str],
) -> str:
    parts = [f"Source file: {source_file}", f"Pages: {', '.join(str(page) for page in pages)}"]
    if section_title:
        parts.append(f"Section: {section_title}")
    if caption:
        parts.append("Table caption: " + " ".join(caption))
    if header:
        parts.append("Table header: " + " | ".join(header))
    if before:
        parts.append("Context before: " + " ".join(before))
    if table_text:
        parts.append("Table:\n" + table_text)
    if after:
        parts.append("Context after: " + " ".join(after))
    if footnote:
        parts.append("Table footnote: " + " ".join(footnote))
    return "\n\n".join(parts)


def base_metadata(
    source_file: str,
    pages: list[int],
    mineru_item_index: int,
    table_header: list[str] | None = None,
    table_caption: list[str] | None = None,
    table_footnote: list[str] | None = None,
    before: list[str] | None = None,
    after: list[str] | None = None,
    part_index: int = 1,
    part_count: int = 1,
) -> dict[str, Any]:
    return {
        "filename": source_file,
        "pages": pages,
        "table_header": table_header or [],
        "table_caption": table_caption or [],
        "table_footnote": table_footnote or [],
        "context_before": before or [],
        "context_after": after or [],
        "table_part_index": part_index,
        "table_part_count": part_count,
        "mineru_item_index": mineru_item_index,
    }


def build_chunks_for_file(
    source_path: Path,
    items: list[dict[str, Any]],
    max_table_rows: int = DEFAULT_MAX_TABLE_ROWS,
    context_window: int = DEFAULT_CONTEXT_WINDOW,
    max_text_chars: int = DEFAULT_MAX_TEXT_CHARS,
) -> list[dict[str, Any]]:
    normalized = normalize_mineru_items(items)
    chunks: list[dict[str, Any]] = []
    text_buffer: list[NormalizedItem] = []

    def flush_text_buffer() -> None:
        nonlocal text_buffer
        if not text_buffer:
            return
        current: list[NormalizedItem] = []
        current_chars = 0
        for item in text_buffer:
            item_len = len(item.text)
            if current and current_chars + item_len > max_text_chars:
                append_text_chunk(chunks, source_path, current)
                current = []
                current_chars = 0
            current.append(item)
            current_chars += item_len
        if current:
            append_text_chunk(chunks, source_path, current)
        text_buffer = []

    for position, item in enumerate(normalized):
        if item.item_type == "table":
            flush_text_buffer()
            chunks.extend(build_table_chunks(source_path, normalized, position, item, max_table_rows, context_window))
        elif item.item_type not in IGNORED_CONTEXT_TYPES:
            text_buffer.append(item)
    flush_text_buffer()

    for ordinal, chunk in enumerate(chunks, start=1):
        chunk["chunk_id"] = f"{source_path.stem}:{ordinal:05d}"
    return chunks


def append_text_chunk(chunks: list[dict[str, Any]], source_path: Path, items: list[NormalizedItem]) -> None:
    pages = sorted({item.page for item in items})
    section_title = next((item.section_title for item in reversed(items) if item.section_title), "")
    text = "\n\n".join(item.text for item in items if item.text)
    chunks.append(
        {
            "chunk_id": "",
            "source_file": source_path.name,
            "source_path": str(source_path),
            "page_start": min(pages),
            "page_end": max(pages),
            "chunk_type": "text",
            "section_title": section_title,
            "text": text,
            "metadata": base_metadata(source_path.name, pages, items[0].index),
        }
    )


def build_table_chunks(
    source_path: Path,
    normalized: list[NormalizedItem],
    position: int,
    item: NormalizedItem,
    max_table_rows: int,
    context_window: int,
) -> list[dict[str, Any]]:
    table = parse_table_html(item.html)
    rows = table.rows
    row_parts = split_rows(rows, max_table_rows)
    before = context_before(normalized, position, context_window)
    after = context_after(normalized, position, context_window)
    pages = [item.page]
    part_count = len(row_parts)
    warnings: list[str] = []
    if not item.html:
        warnings.append("table_html_missing")
    if item.html and not table.header:
        warnings.append("table_header_missing")
    if item.html and not rows:
        warnings.append("table_body_missing")

    chunks: list[dict[str, Any]] = []
    for part_index, part_rows in enumerate(row_parts, start=1):
        table_text = render_table(table.header, part_rows) if item.html else table.raw_text
        if not table_text and item.image_path:
            table_text = f"Table image: {item.image_path}"
        metadata = base_metadata(
            source_path.name,
            pages,
            item.index,
            table_header=table.header,
            table_caption=item.caption,
            table_footnote=item.footnote,
            before=before,
            after=after,
            part_index=part_index,
            part_count=part_count,
        )
        if item.image_path:
            metadata["img_path"] = item.image_path
        if warnings:
            metadata["parse_warning"] = warnings
        chunks.append(
            {
                "chunk_id": "",
                "source_file": source_path.name,
                "source_path": str(source_path),
                "page_start": item.page,
                "page_end": item.page,
                "chunk_type": "table",
                "section_title": item.section_title,
                "text": build_table_text(
                    source_path.name,
                    pages,
                    item.section_title,
                    item.caption or [],
                    table.header,
                    before,
                    table_text,
                    after,
                    item.footnote or [],
                ),
                "metadata": metadata,
            }
        )
    return chunks


def run_mineru(pdf_path: Path, output_dir: Path, force: bool = False) -> None:
    if not force and find_content_list(output_dir, pdf_path.stem):
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        "mineru",
        "-p",
        str(pdf_path),
        "-o",
        str(output_dir),
        "-m",
        "auto",
        "-b",
        "pipeline",
        "-l",
        "ch",
        "-t",
        "true",
        "-f",
        "false",
    ]
    subprocess.run(command, check=True)


def find_content_list(mineru_dir: Path, pdf_stem: str) -> Path | None:
    candidates = sorted(mineru_dir.rglob(f"{pdf_stem}_content_list_v2.json"))
    if candidates:
        return candidates[0]
    candidates = sorted(mineru_dir.rglob(f"{pdf_stem}_content_list.json"))
    return candidates[0] if candidates else None


def load_content_items(content_path: Path) -> list[dict[str, Any]]:
    data = json.loads(content_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"MinerU content list must be a JSON array: {content_path}")

    flattened: list[dict[str, Any]] = []
    for item in data:
        if isinstance(item, dict):
            flattened.append(item)
        elif isinstance(item, list):
            flattened.extend(sub_item for sub_item in item if isinstance(sub_item, dict))
    return flattened


def write_jsonl(path: Path, chunks: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for chunk in chunks:
            file.write(json.dumps(chunk, ensure_ascii=False) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def summarize_file(pdf_path: Path, chunks: list[dict[str, Any]], content_path: Path | None, errors: list[str]) -> dict[str, Any]:
    text_count = sum(1 for chunk in chunks if chunk["chunk_type"] == "text")
    table_count = sum(1 for chunk in chunks if chunk["chunk_type"] == "table")
    split_table_count = sum(
        1
        for chunk in chunks
        if chunk["chunk_type"] == "table" and chunk["metadata"].get("table_part_count", 1) > 1
    )
    page_end = max((chunk["page_end"] for chunk in chunks), default=0)
    return {
        "source_file": pdf_path.name,
        "source_path": str(pdf_path),
        "content_list_path": str(content_path) if content_path else "",
        "page_count_seen": page_end,
        "chunk_count": len(chunks),
        "text_chunk_count": text_count,
        "table_chunk_count": table_count,
        "split_table_chunk_count": split_table_count,
        "errors": errors,
    }


def process_documents(
    docs_dir: Path,
    mineru_dir: Path,
    output_jsonl: Path,
    by_file_dir: Path,
    skip_mineru: bool,
    force_parse: bool,
    max_table_rows: int,
    context_window: int,
) -> dict[str, Any]:
    pdf_paths = sorted(docs_dir.glob("*.pdf"))
    all_chunks: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []

    for pdf_path in pdf_paths:
        errors: list[str] = []
        if not skip_mineru:
            try:
                run_mineru(pdf_path, mineru_dir, force=force_parse)
            except (OSError, subprocess.CalledProcessError) as exc:
                errors.append(str(exc))
        content_path = find_content_list(mineru_dir, pdf_path.stem)
        file_chunks: list[dict[str, Any]] = []
        if content_path:
            try:
                items = load_content_items(content_path)
                file_chunks = build_chunks_for_file(
                    pdf_path,
                    items,
                    max_table_rows=max_table_rows,
                    context_window=context_window,
                )
            except (json.JSONDecodeError, ValueError, OSError) as exc:
                errors.append(str(exc))
        else:
            errors.append("MinerU content list not found")
        write_jsonl(by_file_dir / f"{pdf_path.stem}.chunks.jsonl", file_chunks)
        summary = summarize_file(pdf_path, file_chunks, content_path, errors)
        write_json(by_file_dir / f"{pdf_path.stem}.summary.json", summary)
        summaries.append(summary)
        all_chunks.extend(file_chunks)

    write_jsonl(output_jsonl, all_chunks)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "docs_dir": str(docs_dir),
        "mineru_dir": str(mineru_dir),
        "output_jsonl": str(output_jsonl),
        "by_file_dir": str(by_file_dir),
        "skip_mineru": skip_mineru,
        "force_parse": force_parse,
        "max_table_rows": max_table_rows,
        "context_window": context_window,
        "pdf_count": len(pdf_paths),
        "chunk_count": len(all_chunks),
        "summaries": summaries,
    }
    write_json(output_jsonl.parent / "manifest.json", manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build RAG-ready JSONL chunks from MinerU PDF output.")
    parser.add_argument("--docs-dir", type=Path, default=DEFAULT_DOCS_DIR)
    parser.add_argument("--mineru-dir", type=Path, default=DEFAULT_MINERU_DIR)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--by-file-dir", type=Path, default=DEFAULT_BY_FILE_DIR)
    parser.add_argument("--force-parse", action="store_true")
    parser.add_argument("--skip-mineru", action="store_true")
    parser.add_argument("--max-table-rows", type=int, default=DEFAULT_MAX_TABLE_ROWS)
    parser.add_argument("--context-window", type=int, default=DEFAULT_CONTEXT_WINDOW)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    manifest = process_documents(
        docs_dir=args.docs_dir,
        mineru_dir=args.mineru_dir,
        output_jsonl=args.output_jsonl,
        by_file_dir=args.by_file_dir,
        skip_mineru=args.skip_mineru,
        force_parse=args.force_parse,
        max_table_rows=args.max_table_rows,
        context_window=args.context_window,
    )
    print(json.dumps({"chunk_count": manifest["chunk_count"], "pdf_count": manifest["pdf_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
