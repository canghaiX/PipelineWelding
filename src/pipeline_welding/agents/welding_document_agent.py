from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from docx import Document


@dataclass(frozen=True)
class WeldingDocumentAgentConfig:
    template_docx_path: Path = Path("data/MHPWPS-062.docx")
    output_dir: Path = Path("result")
    output_prefix: str = "welding_standard_filled"


class WeldingDocumentAgent:
    """Fills a WPS-style DOCX from the standard-agent JSON result."""

    def __init__(self, config: WeldingDocumentAgentConfig | None = None) -> None:
        self.config = config or WeldingDocumentAgentConfig()

    def build_document(self, standard_result: dict[str, Any]) -> Path:
        template_path = self.config.template_docx_path
        if not template_path.exists():
            raise FileNotFoundError(f"Template DOCX not found: {template_path}")

        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        document = Document(str(template_path))

        fields = self._extract_input_fields(standard_result)
        self._fill_known_paragraphs(document, fields)
        self._append_standard_summary(document, standard_result)

        output_path = self._build_output_path()
        document.save(str(output_path))
        print(f"已生成焊接标准文档：{output_path}")
        return output_path

    @staticmethod
    def _extract_input_fields(standard_result: dict[str, Any]) -> dict[str, str]:
        fields = standard_result.get("input", {})
        if not isinstance(fields, dict):
            return {}
        return {key: str(value).strip() for key, value in fields.items()}

    def _fill_known_paragraphs(self, document: Document, fields: dict[str, str]) -> None:
        replacements = {
            "焊接方法": self._line_value("焊接方法", fields.get("welding_process")),
            "坡口形式": self._line_value("坡口形式", fields.get("joint_type")),
            "类别号": self._base_material_line(fields.get("base_material")),
            "对接焊缝焊件母材厚度范围": self._line_value(
                "对接焊缝焊件母材厚度范围",
                fields.get("base_thickness_or_diameter"),
            ),
            "管子直径、壁厚范围": self._line_value(
                "管子直径、壁厚范围：对接焊缝",
                fields.get("base_thickness_or_diameter"),
            ),
        }

        for paragraph in document.paragraphs:
            text = paragraph.text.strip()
            for prefix, value in replacements.items():
                if value and text.startswith(prefix):
                    paragraph.text = value
                    break

        for table in document.tables:
            for row in table.rows:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        text = paragraph.text.strip()
                        for prefix, value in replacements.items():
                            if value and text.startswith(prefix):
                                paragraph.text = value
                                break

    @staticmethod
    def _line_value(label: str, value: str | None) -> str:
        if not value:
            return ""
        return f"{label}{value}"

    @staticmethod
    def _base_material_line(value: str | None) -> str:
        if not value:
            return ""
        return f"母材：标准号/材料代号 {value}"

    def _append_standard_summary(self, document: Document, standard_result: dict[str, Any]) -> None:
        document.add_page_break()
        document.add_heading("智能体填充信息", level=1)

        fields = standard_result.get("input", {})
        standard = standard_result.get("pipeline_welding_standard", {})
        mcp_search = standard_result.get("mcp_search", {})

        document.add_heading("一、已识别焊接信息", level=2)
        for key, label in (
            ("welding_process", "焊接工艺"),
            ("welding_object", "焊接对象"),
            ("joint_type", "接头形式"),
            ("base_material", "母材牌号/规格"),
            ("base_thickness_or_diameter", "母材厚度/管径"),
        ):
            document.add_paragraph(f"{label}：{fields.get(key, '')}")

        document.add_heading("二、标准草案关键控制要求", level=2)
        for item in standard.get("required_controls", []):
            self._add_paragraph(document, str(item), style="List Bullet")

        document.add_heading("三、MCP 搜索依据", level=2)
        results = mcp_search.get("results", {})
        if isinstance(results, dict):
            for query, items in results.items():
                document.add_paragraph(f"检索式：{query}")
                if isinstance(items, list):
                    for item in items[:5]:
                        title = item.get("title", "")
                        url = item.get("url", "")
                        snippet = item.get("snippet", "")
                        self._add_paragraph(document, f"{title} {url}\n{snippet}", style="List Bullet")

        document.add_heading("四、标准 JSON 汇总", level=2)
        document.add_paragraph(json.dumps(standard_result, ensure_ascii=False, indent=2))

    def _build_output_path(self) -> Path:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.config.output_dir / f"{self.config.output_prefix}_{timestamp}.docx"

    @staticmethod
    def _add_paragraph(document: Document, text: str, style: str | None = None) -> None:
        try:
            document.add_paragraph(text, style=style)
        except KeyError:
            document.add_paragraph(text)


def build_welding_document_agent(
    config: WeldingDocumentAgentConfig | None = None,
) -> WeldingDocumentAgent:
    return WeldingDocumentAgent(config=config)


def build_welding_document_agent_from_config(config: dict[str, Any]) -> WeldingDocumentAgent:
    template_config = config.get("template", {})
    output_config = config.get("output", {})
    return WeldingDocumentAgent(
        WeldingDocumentAgentConfig(
            template_docx_path=Path(template_config.get("docx_path", "data/MHPWPS-062.docx")),
            output_dir=Path(output_config.get("dir", "result")),
            output_prefix=output_config.get("prefix", "welding_standard_filled"),
        )
    )
