from __future__ import annotations

import sys
import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_pdf_rag_chunks.py"
SPEC = importlib.util.spec_from_file_location("build_pdf_rag_chunks", SCRIPT_PATH)
assert SPEC and SPEC.loader
rag_chunks = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = rag_chunks
SPEC.loader.exec_module(rag_chunks)


def sample_items(table_html: str) -> list[dict]:
    return [
        {
            "type": "title",
            "content": {"title_content": "4 焊接材料"},
            "page_idx": 0,
        },
        {
            "type": "paragraph",
            "content": {"paragraph_content": "焊材应符合设计文件和相关标准要求。"},
            "page_idx": 0,
        },
        {
            "type": "paragraph",
            "content": {"paragraph_content": "下表列出了常用焊材的适用范围。"},
            "page_idx": 0,
        },
        {
            "type": "table",
            "content": {
                "table_caption": ["表 4.1 常用焊材"],
                "table_footnote": ["注：按实际工况复核。"],
                "html": table_html,
                "image_source": {"path": "images/table_1.png"},
            },
            "page_idx": 1,
        },
        {
            "type": "paragraph",
            "content": {"paragraph_content": "焊接前应检查焊材批号和质量证明书。"},
            "page_idx": 1,
        },
    ]


def test_parse_table_html_extracts_header_from_thead() -> None:
    table = rag_chunks.parse_table_html(
        "<table><thead><tr><th>牌号</th><th>规格</th></tr></thead>"
        "<tbody><tr><td>E4315</td><td>3.2 mm</td></tr></tbody></table>"
    )

    assert table.header == ["牌号", "规格"]
    assert table.rows == [["E4315", "3.2 mm"]]


def test_large_table_split_repeats_header_and_source_metadata() -> None:
    rows = "".join(f"<tr><td>E43{i}</td><td>{i}.2 mm</td></tr>" for i in range(5))
    html = f"<table><tr><th>牌号</th><th>规格</th></tr>{rows}</table>"

    chunks = rag_chunks.build_chunks_for_file(
        Path("docs/常用焊材汇总.pdf"),
        sample_items(html),
        max_table_rows=2,
        context_window=2,
    )
    table_chunks = [chunk for chunk in chunks if chunk["chunk_type"] == "table"]

    assert len(table_chunks) == 3
    for index, chunk in enumerate(table_chunks, start=1):
        assert chunk["source_file"] == "常用焊材汇总.pdf"
        assert chunk["page_start"] == 2
        assert chunk["metadata"]["pages"] == [2]
        assert chunk["metadata"]["table_header"] == ["牌号", "规格"]
        assert chunk["metadata"]["table_part_index"] == index
        assert chunk["metadata"]["table_part_count"] == 3
        assert "Table header: 牌号 | 规格" in chunk["text"]


def test_table_chunk_contains_before_and_after_context() -> None:
    html = "<table><tr><th>牌号</th><th>用途</th></tr><tr><td>ER50-6</td><td>打底</td></tr></table>"

    chunks = rag_chunks.build_chunks_for_file(
        Path("docs/钢质 管 道 焊 接 规 程.pdf"),
        sample_items(html),
        max_table_rows=10,
        context_window=2,
    )
    table_chunk = next(chunk for chunk in chunks if chunk["chunk_type"] == "table")

    assert table_chunk["section_title"] == "4 焊接材料"
    assert table_chunk["metadata"]["context_before"] == [
        "焊材应符合设计文件和相关标准要求。",
        "下表列出了常用焊材的适用范围。",
    ]
    assert table_chunk["metadata"]["context_after"] == ["焊接前应检查焊材批号和质量证明书。"]
    assert "Context before:" in table_chunk["text"]
    assert "Context after:" in table_chunk["text"]


def test_chunks_have_required_schema_fields() -> None:
    html = "<table><tr><th>牌号</th></tr><tr><td>E4315</td></tr></table>"
    chunks = rag_chunks.build_chunks_for_file(Path("docs/GB50236-2011.pdf"), sample_items(html))
    required = {
        "chunk_id",
        "source_file",
        "source_path",
        "page_start",
        "page_end",
        "chunk_type",
        "section_title",
        "text",
        "metadata",
    }
    metadata_required = {
        "filename",
        "pages",
        "table_header",
        "table_caption",
        "table_footnote",
        "context_before",
        "context_after",
        "table_part_index",
        "table_part_count",
        "mineru_item_index",
    }

    assert chunks
    for chunk in chunks:
        assert required == set(chunk)
        assert metadata_required.issubset(chunk["metadata"])
        assert chunk["metadata"]["filename"] == chunk["source_file"]
        assert chunk["metadata"]["pages"]


def test_load_content_items_flattens_mineru_v2_page_lists(tmp_path: Path) -> None:
    path = tmp_path / "sample_content_list_v2.json"
    path.write_text(
        """
        [
          [{"type": "title", "content": {"title_content": "第一页"}, "page_idx": 0}],
          [{"type": "paragraph", "content": {"paragraph_content": "第二页正文"}, "page_idx": 1}]
        ]
        """,
        encoding="utf-8",
    )

    items = rag_chunks.load_content_items(path)

    assert [item["type"] for item in items] == ["title", "paragraph"]
    assert [item["page_idx"] for item in items] == [0, 1]


def test_v2_text_parts_are_rendered_as_plain_text() -> None:
    items = [
        [
            {
                "type": "title",
                "content": {"title_content": [{"type": "text", "content": "焊接材料"}]},
                "page_idx": 0,
            },
            {
                "type": "paragraph",
                "content": {"paragraph_content": [{"type": "text", "content": "正文内容"}]},
                "page_idx": 0,
            },
        ]
    ]
    chunks = rag_chunks.build_chunks_for_file(Path("docs/sample.pdf"), items[0])

    assert chunks[0]["section_title"] == "焊接材料"
    assert "{'type':" not in chunks[0]["text"]
    assert chunks[0]["text"] == "焊接材料\n\n正文内容"
