from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any

from dotenv import load_dotenv

from pipeline_welding.documents import read_docx_text
from pipeline_welding.mcp import McpSearchClient, McpSearchConfig, SearchResult


STANDARD_FIELDS = (
    "welding_process",
    "welding_object",
    "joint_type",
    "base_material",
    "base_thickness_or_diameter",
)


@dataclass(frozen=True)
class WeldingStandardAgentConfig:
    reference_docx_path: Path = Path("data/MHPWPS-062.docx")
    max_reference_chars: int = 4000
    max_reference_query_chars: int = 1000


class WeldingStandardAgent:
    """Builds template document fields from re-ask JSON and MCP search evidence."""

    def __init__(
        self,
        search_client: McpSearchClient | None = None,
        config: WeldingStandardAgentConfig | None = None,
    ) -> None:
        self.search_client = search_client
        self.config = config or WeldingStandardAgentConfig()

    def build_standard(self, welding_json: dict[str, Any]) -> dict[str, Any]:
        result = asyncio.run(self.build_standard_async(welding_json))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    async def build_standard_async(self, welding_json: dict[str, Any]) -> dict[str, Any]:
        normalized_input = self._normalize_welding_json(welding_json)
        reference_text = self._load_reference_text()
        search_queries = self._build_search_queries(normalized_input, reference_text)
        search_results = await self._run_search(search_queries)
        document_fields = self._build_document_fields(normalized_input, search_results)

        return {"document_fields": document_fields}

    @staticmethod
    def _normalize_welding_json(welding_json: dict[str, Any]) -> dict[str, str]:
        fields = welding_json.get("fields") if isinstance(welding_json.get("fields"), dict) else welding_json
        return {key: str(fields.get(key, "")).strip() for key in STANDARD_FIELDS}

    @staticmethod
    def _validate_input(fields: dict[str, str]) -> dict[str, Any]:
        missing_keys = [key for key in STANDARD_FIELDS if not fields.get(key)]
        return {"complete": not missing_keys, "missing_keys": missing_keys}

    def _load_reference_text(self) -> str:
        try:
            return read_docx_text(self.config.reference_docx_path)
        except FileNotFoundError:
            return ""

    def _build_search_queries(self, fields: dict[str, str], reference_text: str) -> list[str]:
        process = fields.get("welding_process", "")
        material = fields.get("base_material", "")
        size = fields.get("base_thickness_or_diameter", "")
        joint_type = fields.get("joint_type", "")
        welding_object = fields.get("welding_object", "")
        base_terms = " ".join(term for term in (process, material, size, joint_type, welding_object) if term)
        return [
            f"{base_terms} WPS 焊接工艺参数",
            f"{process} {material} {joint_type} 电流 电压 焊接速度 线能量 焊材",
            f"{material} {size} 管道焊接 预热温度 层间温度 保护气",
        ]

    def _compact_reference_for_query(self, reference_text: str) -> str:
        compacted = " ".join(reference_text.split())
        return compacted[: self.config.max_reference_query_chars]

    async def _run_search(self, queries: list[str]) -> dict[str, list[SearchResult]]:
        if self.search_client is None:
            return {query: [] for query in queries}

        results: dict[str, list[SearchResult]] = {}
        for query in queries:
            try:
                results[query] = await self.search_client.search(query)
            except Exception as exc:
                results[query] = [
                    SearchResult(
                        title="",
                        snippet=f"error: {exc}",
                        raw={"error": str(exc)},
                    )
                ]
        return results

    def _build_document_fields(
        self,
        fields: dict[str, str],
        search_results: dict[str, list[SearchResult]],
    ) -> dict[str, str]:
        evidence_text = self._collect_clean_search_text(search_results)
        base_material_text = fields.get("base_material", "")
        searchable_text = "\n".join(part for part in (base_material_text, evidence_text) if part)
        document_fields = {
            "wps_no": self._first_match(evidence_text, (r"(?:WPS|PWPS)[-\s]?\d+",)),
            "pqr_no": self._first_match(evidence_text, (r"(?:PQR|WPQR|PQR-)[-\s]?[A-Z0-9-]+",)),
            "welding_process": fields.get("welding_process", ""),
            "mechanization": self._first_match(evidence_text, (r"(手工|半自动|自动|机械化)",)) or self._default_mechanization(fields.get("welding_process", "")),
            "welding_object": fields.get("welding_object", ""),
            "groove_type": fields.get("joint_type", ""),
            "backing": self._first_match(evidence_text, (r"(?:衬垫|backing)[^\n:：]*[:：]?\s*([A-Za-z0-9#./+\-\u4e00-\u9fff]+)",)),
            "joint_other": "/",
            "base_material": fields.get("base_material", ""),
            "base_material_category": self._first_match(searchable_text, (r"(?:P-No\.?\s*\d+|Fe-\d+)",)),
            "base_material_group": self._first_match(searchable_text, (r"(?:Group\s*\d+|Gr\.?\s*\d+|Fe-\d+-\d+)",)),
            "base_material_standard": self._first_match(searchable_text, (r"(?:ASTM\s*A\d+|ASME\s*SA-?\d+|GB/T\s*\d+(?:\.\d+)?)",)),
            "base_material_grade": fields.get("base_material", ""),
            "base_thickness_or_diameter": fields.get("base_thickness_or_diameter", ""),
            "base_thickness_range_butt": fields.get("base_thickness_or_diameter", ""),
            "base_thickness_range_fillet": "/",
            "pipe_diameter_thickness_butt": fields.get("base_thickness_or_diameter", ""),
            "pipe_diameter_thickness_fillet": "/",
            "preheat_temperature": self._first_match(evidence_text, (r"预热温度[^\d≥≤]*([≥≤]?\s*\d+\s*℃?)",)),
            "interpass_temperature": self._first_match(evidence_text, (r"层间温度[^\d≥≤]*([≥≤]?\s*\d+\s*℃?)", r"道间温度[^\d≥≤]*([≥≤]?\s*\d+\s*℃?)")),
            "current": self._first_match(evidence_text, (r"电流[^\d]*(\d+\s*[-~～]\s*\d+\s*A?)",)),
            "voltage": self._first_match(evidence_text, (r"电压[^\d]*(\d+\s*[-~～]\s*\d+\s*V?)",)),
            "welding_speed": self._first_match(evidence_text, (r"焊接速度[^\d]*(\d+\s*[-~～]\s*\d+\s*(?:mm/min)?)",)),
            "heat_input": self._first_match(evidence_text, (r"线能量[^\d]*(\d+(?:\.\d+)?\s*(?:kJ/cm)?)",)),
            "filler_metal": self._first_match(evidence_text, (r"(E\d{3,4}[A-Z0-9-]*)",)),
            "filler_diameter": self._first_match(evidence_text, (r"(?:φ|Φ)\s*(\d+(?:\.\d+)?\s*mm)",)),
            "filler_standard": self._first_match(evidence_text, (r"(AWS\s*A\d+(?:\.\d+)?|GB/T\s*\d+(?:\.\d+)?)",)),
            "filler_category": self._first_match(evidence_text, (r"(焊丝|焊条|焊剂|药芯焊丝)",)),
            "filler_model": self._first_match(evidence_text, (r"(E\d{3,4}[A-Z0-9-]*)",)),
            "filler_trade_name": self._first_match(evidence_text, (r"(E\d{3,4}[A-Z0-9-]*)",)),
            "filler_class": self._first_match(evidence_text, (r"(?:F-No\.?\s*\d+|A-No\.?\s*\d+)",)),
            "butt_weld_position": self._first_match(evidence_text, (r"(?:1G|2G|5G|6G|平焊|横焊|立焊|仰焊)",)),
            "vertical_direction": self._first_match(evidence_text, (r"(向上|向下|uphill|downhill)",)),
            "pwht_temperature": "/",
            "pwht_time": "/",
            "polarity": self._first_match(evidence_text, (r"(反接|正接|DCEN|DCEP|EP|EN)",)),
            "shielding_gas": self._first_match(evidence_text, (r"(CO2|二氧化碳|Ar|氩气|混合气)",)),
            "shielding_gas_mix": "/",
            "gas_flow": self._first_match(evidence_text, (r"(\d+\s*[-~～]\s*\d+\s*L/min)",)),
            "trailing_gas": "/",
            "backing_gas": "/",
            "current_type": self._first_match(evidence_text, (r"(AC|DC|直流|交流)",)),
            "tungsten_electrode": self._first_match(evidence_text, (r"(?:钨极)[^\n:：]*[:：]?\s*([A-Za-z0-9#./+\-\u4e00-\u9fff]+)",)),
            "nozzle_diameter": self._first_match(evidence_text, (r"(?:喷嘴)[^\d]*(\d+(?:\.\d+)?\s*mm)",)),
            "arc_type": self._first_match(evidence_text, (r"(短路弧|喷射弧|脉冲弧|globular|spray|short circuit)",)),
            "wire_feed_speed": "/",
            "weaving": self._first_match(evidence_text, (r"(摆动焊|不摆动焊)",)),
            "cleaning": self._first_match(evidence_text, (r"(?:清理|clean)[^\n。；;]*",)),
            "back_gouging": "/",
            "single_or_multi_pass": self._first_match(evidence_text, (r"(单道焊|多道焊|single pass|multi pass)",)),
            "single_or_multi_wire": self._first_match(evidence_text, (r"(单丝|多丝|single wire|multi wire)",)),
            "contact_tip_distance": self._first_match(evidence_text, (r"(\d+\s*[-~～]\s*\d+\s*mm)",)),
            "peening": "/",
            "technical_other": "/",
        }
        self._add_welding_bead_fields(document_fields)
        return {key: self._clean_document_value(value) for key, value in document_fields.items()}

    @staticmethod
    def _add_welding_bead_fields(document_fields: dict[str, str]) -> None:
        bead_defaults = {
            "process": document_fields.get("welding_process", ""),
            "filler_metal": document_fields.get("filler_trade_name") or document_fields.get("filler_metal", ""),
            "diameter": document_fields.get("filler_diameter", ""),
            "polarity": document_fields.get("polarity", ""),
            "current": document_fields.get("current", ""),
            "voltage": document_fields.get("voltage", ""),
            "speed": document_fields.get("welding_speed", ""),
            "heat_input": document_fields.get("heat_input", ""),
        }
        for bead_no in (1, 2):
            for field_name, value in bead_defaults.items():
                document_fields[f"bead_{bead_no}_{field_name}"] = value

    @staticmethod
    def _clean_document_value(value: Any) -> str:
        text = str(value).strip() if value is not None else ""
        lowered = text.lower()
        blocked = ("not found", "unknown tool", "unknown too", "error", "missing")
        if not text or any(item in lowered for item in blocked):
            return "/"
        return text

    @staticmethod
    def _default_mechanization(welding_process: str) -> str:
        normalized = welding_process.upper()
        manual_processes = ("SMAW", "GTAW")
        semi_auto_processes = ("GMAW", "FCAW")
        auto_processes = ("SAW",)
        if any(process in normalized for process in manual_processes):
            return "手工"
        if any(process in normalized for process in semi_auto_processes):
            return "半自动"
        if any(process in normalized for process in auto_processes):
            return "自动"
        return ""

    @staticmethod
    def _collect_clean_search_text(search_results: dict[str, list[SearchResult]]) -> str:
        parts = []
        for results in search_results.values():
            for result in results:
                parts.extend([result.title, result.snippet])
        return "\n".join(part for part in parts if WeldingStandardAgent._is_clean_text(part))

    @staticmethod
    def _is_clean_text(text: str) -> bool:
        lowered = text.lower()
        blocked = ("not found", "unknown tool", "unknown too", "error", "missing")
        return bool(text.strip()) and not any(item in lowered for item in blocked)

    @staticmethod
    def _first_match(text: str, patterns: tuple[str, ...]) -> str:
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                value = match.group(1) if match.groups() else match.group(0)
                return value.strip().replace(" ", "")
        return ""


def build_welding_standard_agent(
    search_client: McpSearchClient | None = None,
) -> WeldingStandardAgent:
    return WeldingStandardAgent(search_client=search_client)


def build_welding_standard_agent_from_config(config: dict[str, Any]) -> WeldingStandardAgent:
    load_dotenv()
    reference_config = config.get("reference", {})
    mcp_config = config.get("mcp_search", {})

    agent_config = WeldingStandardAgentConfig(
        reference_docx_path=Path(reference_config.get("wps_docx_path", "data/MHPWPS-062.docx")),
        max_reference_chars=int(reference_config.get("max_reference_chars", 4000)),
        max_reference_query_chars=int(reference_config.get("max_reference_query_chars", 1000)),
    )
    search_client = None
    if mcp_config.get("enabled"):
        search_client = McpSearchClient(
            McpSearchConfig(
                transport=_resolve_env(mcp_config.get("transport", "stdio")),
                tool_name=_resolve_env(mcp_config.get("tool_name", "search")),
                command=_resolve_env(mcp_config.get("command", "")),
                args=tuple(_resolve_env(str(item)) for item in mcp_config.get("args", [])),
                url=_resolve_env(mcp_config.get("url", "")),
                max_results=int(mcp_config.get("max_results", 5)),
            )
        )

    return WeldingStandardAgent(search_client=search_client, config=agent_config)


def _resolve_env(value: str) -> str:
    pattern = re.compile(r"\$\{([A-Z0-9_]+)\}")

    def replace(match: re.Match[str]) -> str:
        return os.getenv(match.group(1), "")

    return pattern.sub(replace, value)
