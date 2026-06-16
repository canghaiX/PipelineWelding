from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any

from dotenv import load_dotenv

from pipeline_welding.config import load_yaml_config
from pipeline_welding.documents import read_docx_text
from pipeline_welding.mcp import McpSearchClient, McpSearchConfig, SearchResult
from pipeline_welding.rag import HybridRagConfig, HybridRagRetriever


STANDARD_FIELDS = (
    "welding_process",
    "welding_object",
    "joint_type",
    "base_material",
    "base_thickness_or_diameter",
)

CLEANING_DEFAULT = "焊前及层间清理至金属光泽，去除油污、铁锈、氧化皮和飞溅物"
ENGLISH_TEMPLATE_MARKERS = (
    "cleaning(brushing",
    "methodofbackgouging",
    "tungstenelectrodesizeandtype",
    "postweldheattreatment",
    "gas(qw-408",
    "modeofmetaltransfer",
    "contacttubetoworkdistance",
    "multipleorsinglepass",
    "multipleorsingleelectrodes",
    "electrodespacing",
    "preheatmaintenance",
    "weldingprogression",
    "ampsandvolts",
)
TECHNICAL_FIELD_KEYS = {
    "cleaning",
    "back_gouging",
    "weaving",
    "weaving_parameter",
    "technical_other",
}

USER_LOCKED_FIELD_MAP = {
    "welding_process": "welding_process",
    "welding_object": "welding_object",
    "joint_type": "joint_type",
    "base_material": "base_material",
    "base_thickness_or_diameter": "base_thickness_or_diameter",
}

FAMILY_HINTS = {
    "industrial_pressure_piping": ("工业管道", "压力管道", "20#", "20钢", "Q345", "Q355", "GB/T20801", "GB50236"),
    "oil_gas_pipeline": ("油气", "长输", "集输", "管线钢", "L245", "L360", "X52", "GB/T9711", "API5L"),
    "asme_aws_reference": ("ASTM", "ASME", "AWS", "A106", "P-NO.1", "P-NO. 1", "API5L"),
}

NEVER_SEARCH_OVERRIDE_FIELDS = {
    "unit_name",
    "prepared_by",
    "prepared_date",
    "reviewed_by",
    "reviewed_date",
    "approved_by",
    "approved_date",
}

SEARCH_OVERRIDABLE_FIELDS = {
    "wps_no",
    "pqr_no",
    "preheat_temperature",
    "interpass_temperature",
    "current",
    "voltage",
    "welding_speed",
    "heat_input",
    "filler_metal",
    "filler_diameter",
    "filler_standard",
    "filler_category",
    "filler_model",
    "filler_trade_name",
    "filler_class",
    "butt_weld_position",
    "vertical_direction",
    "polarity",
    "shielding_gas",
    "shielding_gas_mix",
    "gas_flow",
    "current_type",
    "tungsten_electrode",
    "nozzle_diameter",
}

NUMERIC_SEARCH_OVERRIDE_FIELDS = {
    "preheat_temperature",
    "interpass_temperature",
    "current",
    "voltage",
    "welding_speed",
    "heat_input",
    "filler_diameter",
    "gas_flow",
    "nozzle_diameter",
}

TRUSTED_EVIDENCE_KEYWORDS = (
    "wps",
    "pwps",
    "pqr",
    "wpqr",
    "asme",
    "aws",
    "astm",
    "gb/t",
    "iso",
    "api",
    "standard",
    "procedure specification",
    "焊接工艺规程",
    "工艺评定",
    "标准",
)

SUPPORTED_WELDING_PROCESSES = ("SMAW", "GTAW", "GMAW", "FCAW", "SAW")
PROCESS_SENSITIVE_FIELDS = {
    "mechanization",
    "filler_metal",
    "filler_diameter",
    "filler_standard",
    "filler_category",
    "filler_model",
    "filler_trade_name",
    "polarity",
    "shielding_gas",
    "shielding_gas_mix",
    "gas_flow",
    "trailing_gas",
    "backing_gas",
    "current_type",
    "tungsten_electrode",
    "nozzle_diameter",
    "arc_type",
    "wire_feed_speed",
    "weaving",
    "single_or_multi_wire",
    "current",
    "voltage",
    "welding_speed",
    "bead_1_process",
    "bead_1_filler_metal",
    "bead_1_diameter",
    "bead_1_polarity",
    "bead_1_current",
    "bead_1_voltage",
    "bead_1_speed",
    "bead_1_heat_input",
    "bead_2_process",
    "bead_2_filler_metal",
    "bead_2_diameter",
    "bead_2_polarity",
    "bead_2_current",
    "bead_2_voltage",
    "bead_2_speed",
    "bead_2_heat_input",
}
FIELD_CANDIDATE_SOURCE_SCORES = {
    "rag_evidence": 90,
    "industry_yaml": 70,
    "verified_search": 65,
    "llm_suggestion": 45,
    "rule_fallback": 30,
}
REFERENCE_PARAMETER_FIELDS = SEARCH_OVERRIDABLE_FIELDS | {
    "bead_1_filler_metal",
    "bead_1_diameter",
    "bead_1_polarity",
    "bead_1_current",
    "bead_1_voltage",
    "bead_1_speed",
    "bead_2_filler_metal",
    "bead_2_diameter",
    "bead_2_polarity",
    "bead_2_current",
    "bead_2_voltage",
    "bead_2_speed",
}
YAML_PROTECTED_FIELDS = {
    "base_material_category",
    "base_material_group",
    "base_material_standard",
    "base_material_grade",
    "mechanization",
    "welding_object",
    "joint_type",
    "backing",
    "joint_other",
    "base_thickness_range_butt",
    "base_thickness_range_fillet",
    "pipe_diameter_thickness_butt",
    "pipe_diameter_thickness_fillet",
    "corrosion_overlay_chemical_composition",
    "corrosion_overlay_other",
}

DOCUMENT_FIELD_KEYS = (
    "unit_name",
    "wps_no",
    "pqr_no",
    "welding_process",
    "welding_object",
    "joint_type",
    "mechanization",
    "groove_type",
    "backing",
    "joint_other",
    "base_material",
    "base_material_category",
    "base_material_group",
    "base_material_standard",
    "base_material_grade",
    "base_thickness_or_diameter",
    "base_thickness_range_butt",
    "base_thickness_range_fillet",
    "pipe_diameter_thickness_butt",
    "pipe_diameter_thickness_fillet",
    "corrosion_overlay_chemical_composition",
    "corrosion_overlay_other",
    "preheat_temperature",
    "interpass_temperature",
    "fillet_weld_position",
    "current",
    "voltage",
    "welding_speed",
    "heat_input",
    "filler_metal",
    "filler_diameter",
    "filler_standard",
    "filler_category",
    "filler_model",
    "filler_trade_name",
    "filler_class",
    "butt_weld_position",
    "vertical_direction",
    "pwht_temperature",
    "pwht_time",
    "polarity",
    "shielding_gas",
    "shielding_gas_mix",
    "gas_flow",
    "trailing_gas",
    "backing_gas",
    "preheat_time",
    "heating_method",
    "current_type",
    "tungsten_electrode",
    "nozzle_diameter",
    "arc_type",
    "wire_feed_speed",
    "weaving",
    "weaving_parameter",
    "cleaning",
    "back_gouging",
    "single_or_multi_pass",
    "single_or_multi_wire",
    "contact_tip_distance",
    "peening",
    "technical_other",
    "prepared_by",
    "prepared_date",
    "reviewed_by",
    "reviewed_date",
    "approved_by",
    "approved_date",
    "bead_1_process",
    "bead_1_filler_metal",
    "bead_1_diameter",
    "bead_1_polarity",
    "bead_1_current",
    "bead_1_voltage",
    "bead_1_speed",
    "bead_1_heat_input",
    "bead_2_process",
    "bead_2_filler_metal",
    "bead_2_diameter",
    "bead_2_polarity",
    "bead_2_current",
    "bead_2_voltage",
    "bead_2_speed",
    "bead_2_heat_input",
)


@dataclass(frozen=True)
class WeldingStandardAgentConfig:
    reference_docx_path: Path = Path("data/MHPWPS-062.docx")
    max_reference_chars: int = 4000
    max_reference_query_chars: int = 1000
    llm_enabled: bool = True
    model_config_path: Path = Path("configs/model_config.yaml")
    prompt_path: Path = Path("prompts/welding_standard_agent_prompt.md")
    max_evidence_chars: int = 9000
    max_sources_per_query: int = 3
    use_industry_defaults: bool = True
    bead_strategy: str = "root_gtaw_fill_smaw"
    default_unknown: str = "/"
    reference_fill_mode: str = "aggressive_reference"
    industry_standards_path: Path = Path("configs/welding_industry_standards.yaml")
    use_industry_standards: bool = True
    allow_verified_search_override: bool = True
    min_evidence_match_score: int = 3
    evidence_decision_mode: str = "balanced"
    min_verified_search_score: int = 4
    allow_verified_network_refine: bool = True
    conflict_policy: str = "prefer_yaml_unless_strong_verified"
    rag_enabled: bool = True
    rag_index_dir: Path = Path("data/rag/faiss")
    rag_embedding_url: str = "http://127.0.0.1:8001/v1/embeddings"
    rag_rerank_url: str = "http://127.0.0.1:8002/rerank"
    rag_embedding_model: str = "bge-m3"
    rag_rerank_model: str = "bge-reranker-v2-m3"
    rag_semantic_top_k: int = 10
    rag_keyword_top_k: int = 10
    rag_fusion_top_k: int = 10
    rag_final_top_k: int = 5
    rag_rrf_k: int = 60


@dataclass(frozen=True)
class FieldCandidate:
    key: str
    value: str
    source_type: str
    basis: str = ""
    confidence: str = "medium"
    match_score: int = 0
    process_match: bool = True
    material_match: bool = True
    field_applicability: str = "applicable"


class WeldingStandardAgent:
    """Builds template document fields from re-ask JSON and MCP search evidence."""

    def __init__(
        self,
        search_client: McpSearchClient | None = None,
        config: WeldingStandardAgentConfig | None = None,
        rag_retriever: Any | None = None,
    ) -> None:
        self.search_client = search_client
        self.config = config or WeldingStandardAgentConfig()
        self.rag_retriever = rag_retriever

    def build_standard(self, welding_json: dict[str, Any]) -> dict[str, Any]:
        result = asyncio.run(self.build_standard_async(welding_json))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result

    async def build_standard_async(self, welding_json: dict[str, Any]) -> dict[str, Any]:
        normalized_input = self._normalize_welding_json(welding_json)
        reference_text = self._load_reference_text()
        rag_query = self._build_rag_query(normalized_input)
        rag_results = self._run_rag(rag_query)
        search_queries = self._build_search_queries(normalized_input, reference_text)
        search_results = await self._run_search(search_queries)
        rag_fields = self._build_rag_fields(normalized_input, rag_results)
        combined_results = self._merge_search_results(rag_results, search_results)
        rule_fields = self._build_document_fields(normalized_input, combined_results)
        industry_fields = self._match_industry_standard_fields(normalized_input)
        verified_search_fields = self._build_verified_search_fields(normalized_input, search_results)
        document_fields = await self._build_document_fields_with_llm(
            normalized_input,
            reference_text,
            rag_results,
            search_results,
            rule_fields,
            rag_fields,
            industry_fields,
            verified_search_fields,
        )

        return {"document_fields": document_fields, "rag_search": self._summarize_search_results(rag_results)}

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
        queries = [
            f"{base_terms} 相似 PWPS WPS 焊接工艺规程",
            f"{process} {material} {joint_type} pipe WPS welding procedure specification",
            f"{process} root pass fill cap {material} {size} PWPS WPS",
            f"{material} P-No Group ASME IX welding material classification",
            f"{process} {material} {joint_type} filler metal electrode wire AWS",
            f"{process} {material} {size} welding current voltage travel speed heat input",
            f"{material} {size} pipe welding preheat interpass temperature shielding gas",
            f"{process} {joint_type} pipeline welding groove backing cleaning multi pass",
        ]
        if "GTAW" in self._split_process_terms(process) and "SMAW" in self._split_process_terms(process):
            queries.extend(
                [
                    f"GTAW root pass SMAW fill cap {material} pipe WPS",
                    "ASTM A106 Gr.B WPS ER70S-6 E7016 E7018 GTAW SMAW",
                    "ASME IX P-No.1 WPS preheat interpass temperature carbon steel pipe",
                ]
            )
        return queries

    def _build_rag_query(self, fields: dict[str, str]) -> str:
        parts = [
            fields.get("welding_process", ""),
            fields.get("welding_object", ""),
            fields.get("joint_type", ""),
            fields.get("base_material", ""),
            fields.get("base_thickness_or_diameter", ""),
            "焊接工艺评定 WPS PWPS 焊材 预热 层间温度 电流 电压 焊接速度 线能量",
        ]
        return " ".join(part for part in parts if part).strip()

    def _run_rag(self, query: str) -> dict[str, list[SearchResult]]:
        if not self.config.rag_enabled or not query:
            return {"rag_evidence": []}
        retriever = self._get_rag_retriever()
        try:
            payload = retriever.search(query)
        except Exception as exc:
            return {
                "rag_evidence": [
                    SearchResult(title="", snippet=f"error: {exc}", raw={"error": str(exc), "query": query})
                ]
            }
        return {"rag_evidence": self._rag_payload_to_search_results(payload)}

    def _get_rag_retriever(self) -> Any:
        if self.rag_retriever is not None:
            return self.rag_retriever
        self.rag_retriever = HybridRagRetriever(
            HybridRagConfig(
                enabled=self.config.rag_enabled,
                index_dir=self.config.rag_index_dir,
                embedding_url=self.config.rag_embedding_url,
                rerank_url=self.config.rag_rerank_url,
                embedding_model=self.config.rag_embedding_model,
                rerank_model=self.config.rag_rerank_model,
                semantic_top_k=self.config.rag_semantic_top_k,
                keyword_top_k=self.config.rag_keyword_top_k,
                fusion_top_k=self.config.rag_fusion_top_k,
                final_top_k=self.config.rag_final_top_k,
                rrf_k=self.config.rag_rrf_k,
            )
        )
        return self.rag_retriever

    def _rag_payload_to_search_results(self, payload: dict[str, Any]) -> list[SearchResult]:
        results: list[SearchResult] = []
        for item in payload.get("results", []):
            if not isinstance(item, dict):
                continue
            chunk = item.get("chunk", {})
            if not isinstance(chunk, dict):
                continue
            title = self._rag_result_title(chunk)
            snippet = self._rag_result_snippet(chunk)
            results.append(
                SearchResult(
                    title=title,
                    snippet=snippet,
                    url=str(chunk.get("source_path", "")),
                    raw={"score": item.get("score"), "chunk": chunk},
                )
            )
        return results

    @staticmethod
    def _rag_result_title(chunk: dict[str, Any]) -> str:
        source_file = str(chunk.get("source_file", ""))
        page_start = chunk.get("page_start")
        page_end = chunk.get("page_end")
        section = str(chunk.get("section_title", ""))
        pages = f"p.{page_start}-{page_end}" if page_start and page_end and page_start != page_end else f"p.{page_start}"
        return " | ".join(part for part in (source_file, pages if page_start else "", section) if part)

    @staticmethod
    def _rag_result_snippet(chunk: dict[str, Any]) -> str:
        metadata = chunk.get("metadata", {}) if isinstance(chunk.get("metadata"), dict) else {}
        table_header = metadata.get("table_header") or []
        context_before = metadata.get("context_before") or []
        context_after = metadata.get("context_after") or []
        parts = [
            f"来源文件: {chunk.get('source_file', '')}",
            f"页码: {chunk.get('page_start', '')}-{chunk.get('page_end', '')}",
            f"章节: {chunk.get('section_title', '')}",
            f"表头: {' | '.join(str(item) for item in table_header)}" if table_header else "",
            f"上文: {' '.join(str(item) for item in context_before)}" if context_before else "",
            str(chunk.get("text", "")),
            f"下文: {' '.join(str(item) for item in context_after)}" if context_after else "",
        ]
        return "\n".join(part for part in parts if part.strip())

    @staticmethod
    def _merge_search_results(
        rag_results: dict[str, list[SearchResult]],
        search_results: dict[str, list[SearchResult]],
    ) -> dict[str, list[SearchResult]]:
        return {**rag_results, **search_results}

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
            "corrosion_overlay_chemical_composition": "/",
            "corrosion_overlay_other": "/",
            "preheat_temperature": self._first_match(evidence_text, (r"预热温度[^\d≥≤]*([≥≤]?\s*\d+\s*℃?)",)),
            "interpass_temperature": self._first_match(evidence_text, (r"层间温度[^\d≥≤]*([≥≤]?\s*\d+\s*℃?)", r"道间温度[^\d≥≤]*([≥≤]?\s*\d+\s*℃?)")),
            "fillet_weld_position": "/",
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
            "preheat_time": "/",
            "heating_method": "/",
            "current_type": self._first_match(evidence_text, (r"(AC|DC|直流|交流)",)),
            "tungsten_electrode": self._first_match(evidence_text, (r"(?:钨极)[^\n:：]*[:：]?\s*([A-Za-z0-9#./+\-\u4e00-\u9fff]+)",)),
            "nozzle_diameter": self._first_match(evidence_text, (r"(?:喷嘴)[^\d]*(\d+(?:\.\d+)?\s*mm)",)),
            "arc_type": self._first_match(evidence_text, (r"(短路弧|喷射弧|脉冲弧|globular|spray|short circuit)",)),
            "wire_feed_speed": "/",
            "weaving": self._first_match(evidence_text, (r"(摆动焊|不摆动焊)",)),
            "weaving_parameter": "/",
            "cleaning": self._first_match(evidence_text, (r"(?:清理|clean)[^\n。；;]*",)),
            "back_gouging": "/",
            "single_or_multi_pass": self._first_match(evidence_text, (r"(单道焊|多道焊|single pass|multi pass)",)),
            "single_or_multi_wire": self._first_match(evidence_text, (r"(单丝|多丝|single wire|multi wire)",)),
            "contact_tip_distance": self._first_match(evidence_text, (r"(\d+\s*[-~～]\s*\d+\s*mm)",)),
            "peening": "/",
            "technical_other": "/",
            "prepared_by": "/",
            "prepared_date": "/",
            "reviewed_by": "/",
            "reviewed_date": "/",
            "approved_by": "/",
            "approved_date": "/",
        }
        self._add_welding_bead_fields(document_fields)
        return {
            key: self._clean_field_value(key, value)
            for key, value in document_fields.items()
        }

    async def _build_document_fields_with_llm(
        self,
        fields: dict[str, str],
        reference_text: str,
        rag_results: dict[str, list[SearchResult]],
        search_results: dict[str, list[SearchResult]],
        fallback_fields: dict[str, str],
        rag_fields: dict[str, str],
        industry_fields: dict[str, str],
        verified_search_fields: dict[str, str],
    ) -> dict[str, str]:
        if not self.config.llm_enabled:
            return self._finalize_document_fields(
                fields,
                fallback_fields,
                industry_fields,
                verified_search_fields,
                {},
                rag_fields=rag_fields,
            )

        try:
            raw_content = await self._call_llm_for_document_fields(
                fields,
                reference_text,
                rag_results,
                search_results,
                fallback_fields,
                rag_fields,
                industry_fields,
                verified_search_fields,
            )
            llm_fields = self._parse_llm_document_fields(raw_content)
        except Exception:
            return self._finalize_document_fields(
                fields,
                fallback_fields,
                industry_fields,
                verified_search_fields,
                {},
                rag_fields=rag_fields,
            )

        return self._finalize_document_fields(
            fields,
            fallback_fields,
            industry_fields,
            verified_search_fields,
            llm_fields,
            rag_fields=rag_fields,
        )

    async def _call_llm_for_document_fields(
        self,
        fields: dict[str, str],
        reference_text: str,
        rag_results: dict[str, list[SearchResult]],
        search_results: dict[str, list[SearchResult]],
        fallback_fields: dict[str, str],
        rag_fields: dict[str, str],
        industry_fields: dict[str, str],
        verified_search_fields: dict[str, str],
    ) -> str:
        from openai import AsyncOpenAI

        model_config = self._load_model_config()
        model = str(model_config.get("model", {}).get("name", "deepseek-chat"))
        temperature = float(model_config.get("model", {}).get("temperature", 0.2))
        max_tokens = int(model_config.get("model", {}).get("max_tokens", 1800))
        timeout = float(model_config.get("model", {}).get("timeout_seconds", 60))
        runtime_config = model_config.get("runtime", {})
        api_key_env = str(runtime_config.get("api_key_env", "DEEPSEEK_API_KEY"))
        base_url_env = str(runtime_config.get("base_url_env", "DEEPSEEK_BASE_URL"))
        api_key = os.getenv(api_key_env)
        base_url = os.getenv(base_url_env) or None
        if not api_key:
            raise RuntimeError(f"Missing {api_key_env}")

        client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        response = await client.chat.completions.create(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": self._build_llm_system_prompt()},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "user_constraints": fields,
                            "template_field_keys": list(DOCUMENT_FIELD_KEYS),
                            "template_reference_excerpt": reference_text[: self.config.max_reference_chars],
                            "rag_evidence": self._summarize_search_results(rag_results),
                            "search_evidence": self._summarize_search_results(search_results),
                            "rule_fallback_fields": fallback_fields,
                            "rag_fields": rag_fields,
                            "industry_standard_fields": industry_fields,
                            "verified_search_fields": verified_search_fields,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        return response.choices[0].message.content or "{}"

    def _load_model_config(self) -> dict[str, Any]:
        config_path = self.config.model_config_path
        if not config_path.is_absolute():
            config_path = Path.cwd() / config_path
        return load_yaml_config(config_path)

    @staticmethod
    def _default_llm_system_prompt() -> str:
        return (
            "你是管道焊接 PWPS 字段生成助手。你的任务是根据用户约束、MCP 搜索到的相似 WPS/PWPS/标准资料、"
            "以及本地 MHPWPS-062.docx 模板字段，生成可填入模板的 document_fields。\n"
            "必须遵守：只输出 JSON 对象；顶层只能需要 document_fields；document_fields 只能包含给定字段 key；"
            "字段值必须是适合表格填写的短文本；不要输出解释、来源、Markdown 或长段落；"
            "优先级必须是：用户约束 > rag_fields > rag_evidence > verified_search_fields > industry_standard_fields > rule_fallback_fields > /；"
            "你只能在 rag_fields、rag_evidence、industry_standard_fields、verified_search_fields、rule_fallback_fields 中已有候选之间选择或归纳兼容短值；"
            "不得凭经验编造未出现在证据中的参数；只有 verified_search_fields 中已经出现且工况匹配的高可信字段才可细化参考参数；"
            "如果不能回答、不适合填写、证据不足、冲突或无法可靠确定，字段值填 /；"
            "不要把 Not found、Unknown tool、Unknown too、error、missing 等错误文本写入字段。"
        )

    def _build_llm_system_prompt(self) -> str:
        prompt_path = self.config.prompt_path
        if not prompt_path.is_absolute():
            prompt_path = Path.cwd() / prompt_path
        try:
            return prompt_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return self._default_llm_system_prompt()

    def _summarize_search_results(self, search_results: dict[str, list[SearchResult]]) -> list[dict[str, str]]:
        evidence: list[dict[str, str]] = []
        total_chars = 0
        for query, results in search_results.items():
            clean_results = [
                result
                for result in results
                if self._is_clean_text(result.title) or self._is_clean_text(result.snippet)
            ][: self.config.max_sources_per_query]
            for result in clean_results:
                title = result.title if self._is_clean_text(result.title) else ""
                snippet = result.snippet if self._is_clean_text(result.snippet) else ""
                item = {
                    "query": query,
                    "title": title[:200],
                    "url": result.url[:300],
                    "snippet": snippet[:1200],
                }
                item_chars = sum(len(value) for value in item.values())
                if total_chars + item_chars > self.config.max_evidence_chars:
                    return evidence
                evidence.append(item)
                total_chars += item_chars
        return evidence

    @staticmethod
    def _parse_llm_document_fields(content: str) -> dict[str, Any]:
        data = json.loads(content)
        if not isinstance(data, dict):
            return {}
        document_fields = data.get("document_fields", data)
        if not isinstance(document_fields, dict):
            return {}
        return document_fields

    def _match_industry_standard_fields(self, fields: dict[str, str]) -> dict[str, str]:
        if not self.config.use_industry_standards:
            return {}

        config_path = self.config.industry_standards_path
        if not config_path.is_absolute():
            config_path = Path.cwd() / config_path
        try:
            data = load_yaml_config(config_path)
        except FileNotFoundError:
            return {}

        process_fields = self._match_process_reference_fields(fields, data)
        standards = data.get("standards", [])
        if not isinstance(standards, list):
            return process_fields

        best_score = 0
        best_fields: dict[str, str] = dict(process_fields)
        for standard in standards:
            if not isinstance(standard, dict):
                continue
            score = self._score_industry_standard_match(
                fields,
                standard.get("match", {}),
                str(standard.get("family", "")),
            )
            document_fields = standard.get("document_fields", {})
            if score > best_score and isinstance(document_fields, dict):
                best_score = score
                best_fields = {
                    **process_fields,
                    **self._normalize_industry_document_fields(document_fields),
                }

        if best_score < self.config.min_evidence_match_score and not best_fields:
            return {}
        size = self._clean_document_value(fields.get("base_thickness_or_diameter"))
        if size != "/":
            best_fields.setdefault("base_thickness_range_butt", size)
            best_fields.setdefault("pipe_diameter_thickness_butt", size)
        return best_fields

    def _match_process_reference_fields(self, fields: dict[str, str], data: dict[str, Any]) -> dict[str, str]:
        packages = data.get("process_reference_packages", {})
        if not isinstance(packages, dict):
            return {}
        process_key = self._process_package_key(fields.get("welding_process", ""))
        package = packages.get(process_key)
        if not isinstance(package, dict):
            return {}
        document_fields = package.get("document_fields", {})
        if not isinstance(document_fields, dict):
            return {}
        return self._normalize_industry_document_fields(document_fields)

    @classmethod
    def _process_package_key(cls, process: str) -> str:
        terms = cls._split_process_terms(process)
        if "GTAW" in terms and "SMAW" in terms:
            return "GTAW+SMAW"
        return terms[0] if terms else ""

    def _score_industry_standard_match(self, fields: dict[str, str], match: Any, family: str = "") -> int:
        if not isinstance(match, dict):
            return 0
        if not self._industry_process_matches(fields.get("welding_process", ""), match):
            return 0
        if not self._industry_material_matches(fields.get("base_material", ""), match):
            return 0
        score = 0
        combined_input = " ".join(fields.values()).upper().replace(" ", "")
        for hint in FAMILY_HINTS.get(family, ()):
            if hint.upper().replace(" ", "") in combined_input:
                score += 1
                break
        process = fields.get("welding_process", "")
        if self._all_terms_present(process, match.get("welding_process_all", [])):
            score += 2
        if self._any_term_present(process, match.get("welding_process_any", [])):
            score += 1
        if self._any_term_present(fields.get("welding_object", ""), match.get("welding_object_any", [])):
            score += 1
        if self._any_term_present(fields.get("joint_type", ""), match.get("joint_type_any", [])):
            score += 1
        if self._any_term_present(fields.get("base_material", ""), match.get("base_material_any", [])):
            score += 2
        return score

    @classmethod
    def _industry_process_matches(cls, process: str, match: dict[str, Any]) -> bool:
        has_process_constraint = bool(match.get("welding_process_all") or match.get("welding_process_any"))
        if not has_process_constraint:
            return True
        process_terms = set(cls._split_process_terms(process))
        all_terms = {str(term).strip().upper() for term in match.get("welding_process_all", []) if str(term).strip()}
        any_terms = {str(term).strip().upper() for term in match.get("welding_process_any", []) if str(term).strip()}
        if all_terms and not all_terms.issubset(process_terms):
            return False
        if any_terms and process_terms.isdisjoint(any_terms):
            return False
        return bool(all_terms or any_terms)

    @classmethod
    def _industry_material_matches(cls, material: str, match: dict[str, Any]) -> bool:
        material_terms = match.get("base_material_any", [])
        if not material_terms:
            return True
        return cls._any_term_present(material, material_terms)

    def _normalize_industry_document_fields(self, document_fields: dict[str, Any]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, value in document_fields.items():
            if key not in DOCUMENT_FIELD_KEYS:
                continue
            field_value = value.get("value") if isinstance(value, dict) else value
            normalized[key] = self._clean_field_value(key, field_value)
        return normalized

    @staticmethod
    def _field_meta_value(value: Any, meta_key: str) -> Any:
        if isinstance(value, dict):
            return value.get(meta_key)
        return None

    def _build_verified_search_fields(
        self,
        fields: dict[str, str],
        search_results: dict[str, list[SearchResult]],
    ) -> dict[str, str]:
        verified_text = self._collect_verified_search_text(fields, search_results)
        if not verified_text:
            return {}
        candidates = self._build_document_fields(fields, self._search_results_from_text(verified_text))
        return {
            key: value
            for key, value in candidates.items()
            if key in SEARCH_OVERRIDABLE_FIELDS
            and self._clean_document_value(value) != "/"
            and self._is_short_fill_value(value)
        }

    def _build_rag_fields(
        self,
        fields: dict[str, str],
        rag_results: dict[str, list[SearchResult]],
    ) -> dict[str, str]:
        rag_text = self._collect_clean_search_text(rag_results)
        if not rag_text:
            return {}
        candidates = self._build_document_fields(fields, self._search_results_from_text(rag_text))
        return {
            key: value
            for key, value in candidates.items()
            if key in DOCUMENT_FIELD_KEYS
            and key not in NEVER_SEARCH_OVERRIDE_FIELDS
            and self._clean_document_value(value) != "/"
            and self._is_short_fill_value(value)
        }

    def _collect_verified_search_text(
        self,
        fields: dict[str, str],
        search_results: dict[str, list[SearchResult]],
    ) -> str:
        parts: list[str] = []
        for results in search_results.values():
            for result in results:
                if self._is_verified_search_result(fields, result):
                    parts.extend(part for part in (result.title, result.snippet) if self._is_clean_text(part))
        return "\n".join(parts)

    def _is_verified_search_result(self, fields: dict[str, str], result: SearchResult) -> bool:
        text = " ".join(part for part in (result.title, result.snippet, result.url) if part)
        if not self._is_clean_text(text):
            return False
        lowered = text.lower()
        if not any(keyword in lowered for keyword in TRUSTED_EVIDENCE_KEYWORDS):
            return False
        if any(blocked in lowered for blocked in ("forum", "reddit", "blog", "question", "问答", "论坛")):
            return False
        return self._score_search_result_match(fields, text) >= self.config.min_evidence_match_score

    def _score_search_result_match(self, fields: dict[str, str], text: str) -> int:
        score = 0
        process = fields.get("welding_process", "")
        for process_value in self._split_process_terms(process):
            if self._contains_term(text, process_value):
                score += 1
        if self._any_term_present(text, self._material_match_terms(fields.get("base_material", ""))):
            score += 2
        if self._contains_term(text, fields.get("joint_type", "")):
            score += 1
        if self._contains_term(text, fields.get("welding_object", "")):
            score += 1
        return score

    @staticmethod
    def _search_results_from_text(text: str) -> dict[str, list[SearchResult]]:
        return {"verified_search_evidence": [SearchResult(title="verified_search_evidence", snippet=text)]}

    @staticmethod
    def _split_process_terms(process: str) -> list[str]:
        normalized = process.upper()
        for separator in ("+", "＋", "/", "、", ",", "，"):
            normalized = normalized.replace(separator, "|")
        return [item.strip() for item in normalized.split("|") if item.strip()]

    @staticmethod
    def _material_match_terms(material: str) -> list[str]:
        terms = [material]
        upper = material.upper()
        for pattern in (r"ASTM\s*A\d+", r"ASME\s*SA-?\d+", r"A\d{2,4}", r"P-NO\.?\s*\d+", r"GR\.?\s*[A-Z0-9]+"):
            terms.extend(match.group(0) for match in re.finditer(pattern, upper, flags=re.IGNORECASE))
        return [term for term in dict.fromkeys(terms) if term.strip()]

    @staticmethod
    def _all_terms_present(text: str, terms: Any) -> bool:
        normalized_terms = [str(term).strip() for term in terms or [] if str(term).strip()]
        return bool(normalized_terms) and all(
            WeldingStandardAgent._contains_term(text, term) for term in normalized_terms
        )

    @staticmethod
    def _any_term_present(text: str, terms: Any) -> bool:
        return any(
            WeldingStandardAgent._contains_term(text, str(term))
            for term in terms or []
            if str(term).strip()
        )

    @staticmethod
    def _contains_term(text: str, term: str) -> bool:
        if not text or not term:
            return False
        return term.strip().upper().replace(" ", "") in text.upper().replace(" ", "")

    @staticmethod
    def _is_short_fill_value(value: Any) -> bool:
        clean_value = WeldingStandardAgent._clean_document_value(value)
        return clean_value != "/" and len(clean_value) <= 80 and "\n" not in clean_value

    def _finalize_document_fields(
        self,
        input_fields: dict[str, str],
        candidate_fields: dict[str, Any],
        industry_fields: dict[str, str] | None = None,
        verified_search_fields: dict[str, str] | None = None,
        llm_fields: dict[str, Any] | None = None,
        rag_fields: dict[str, str] | None = None,
    ) -> dict[str, str]:
        rag_fields = rag_fields or {}
        industry_fields = industry_fields or {}
        verified_search_fields = verified_search_fields or {}
        llm_fields = llm_fields or {}
        rule_fields = self._filter_rule_fallback_fields(candidate_fields)
        if self.config.use_industry_standards:
            effective_industry_fields = dict(industry_fields)
        else:
            effective_industry_fields = {}
        if not effective_industry_fields and self.config.use_industry_defaults:
            default_fields = {
                key: self.config.default_unknown
                for key in DOCUMENT_FIELD_KEYS
            }
            self._force_user_input_fields(default_fields, input_fields)
            self._apply_industry_defaults(default_fields)
            effective_industry_fields = {
                key: value
                for key, value in default_fields.items()
                if self._clean_document_value(value) != "/"
            }

        finalized = self._resolve_evidence_fields(
            input_fields,
            rule_fields,
            effective_industry_fields,
            verified_search_fields,
            llm_fields,
            rag_fields,
        )

        self._force_user_input_fields(finalized, input_fields)
        self._enforce_process_consistency(finalized)
        if finalized["groove_type"] == "/":
            finalized["groove_type"] = finalized["joint_type"]
        if finalized["base_material_grade"] == "/":
            finalized["base_material_grade"] = finalized["base_material"]
        if finalized["base_thickness_range_butt"] == "/":
            finalized["base_thickness_range_butt"] = finalized["base_thickness_or_diameter"]
        if finalized["pipe_diameter_thickness_butt"] == "/":
            finalized["pipe_diameter_thickness_butt"] = finalized["base_thickness_or_diameter"]
        if finalized["mechanization"] == "/":
            finalized["mechanization"] = self._clean_document_value(
                self._default_mechanization(finalized["welding_process"])
            )
        self._force_forbidden_unknown_fields(finalized)
        self._add_welding_bead_fields(finalized)
        self._enforce_process_consistency(finalized)
        return {
            key: self._clean_field_value(key, finalized.get(key))
            for key in DOCUMENT_FIELD_KEYS
        }

    def _resolve_evidence_fields(
        self,
        input_fields: dict[str, str],
        rule_fields: dict[str, Any],
        industry_fields: dict[str, str],
        verified_search_fields: dict[str, str],
        llm_fields: dict[str, Any],
        rag_fields: dict[str, str],
    ) -> dict[str, str]:
        resolved = {
            key: self.config.default_unknown
            for key in DOCUMENT_FIELD_KEYS
        }
        for key in DOCUMENT_FIELD_KEYS:
            if key in USER_LOCKED_FIELD_MAP.values() or key in NEVER_SEARCH_OVERRIDE_FIELDS:
                continue
            candidates = self._build_field_candidates(
                key,
                input_fields,
                rule_fields,
                industry_fields,
                verified_search_fields,
                llm_fields,
                rag_fields,
            )
            selected = self._select_field_candidate(key, candidates)
            if selected:
                resolved[key] = selected.value
        return resolved

    def _build_field_candidates(
        self,
        key: str,
        input_fields: dict[str, str],
        rule_fields: dict[str, Any],
        industry_fields: dict[str, str],
        verified_search_fields: dict[str, str],
        llm_fields: dict[str, Any],
        rag_fields: dict[str, str],
    ) -> list[FieldCandidate]:
        candidates: list[FieldCandidate] = []
        self._append_field_candidate(candidates, key, rag_fields.get(key), "rag_evidence", input_fields)
        self._append_field_candidate(candidates, key, industry_fields.get(key), "industry_yaml", input_fields)
        self._append_field_candidate(candidates, key, rule_fields.get(key), "rule_fallback", input_fields)
        if self.config.allow_verified_network_refine:
            self._append_field_candidate(
                candidates,
                key,
                verified_search_fields.get(key),
                "verified_search",
                input_fields,
            )
        if self._llm_value_has_support(key, llm_fields.get(key), rag_fields, industry_fields, verified_search_fields, rule_fields):
            self._append_field_candidate(candidates, key, llm_fields.get(key), "llm_suggestion", input_fields)
        return candidates

    def _append_field_candidate(
        self,
        candidates: list[FieldCandidate],
        key: str,
        value: Any,
        source_type: str,
        input_fields: dict[str, str],
    ) -> None:
        if key not in DOCUMENT_FIELD_KEYS or key in NEVER_SEARCH_OVERRIDE_FIELDS:
            return
        clean_value = self._clean_field_value(key, value)
        if clean_value == "/" or not self._is_short_fill_value(clean_value):
            return
        process_match = self._field_value_matches_process(input_fields, key, clean_value)
        material_match = self._field_value_matches_material(input_fields, clean_value)
        if key in PROCESS_SENSITIVE_FIELDS and not process_match:
            return
        if source_type == "verified_search" and not self._verified_candidate_allowed(key, clean_value, input_fields):
            return
        field_applicability = "applicable"
        if key in PROCESS_SENSITIVE_FIELDS and process_match:
            field_applicability = "process_matched"
        candidates.append(
            FieldCandidate(
                key=key,
                value=clean_value,
                source_type=source_type,
                basis=self._candidate_basis(source_type),
                confidence=self._candidate_confidence(source_type),
                match_score=self._candidate_match_score(
                    source_type,
                    key,
                    clean_value,
                    process_match,
                    material_match,
                ),
                process_match=process_match,
                material_match=material_match,
                field_applicability=field_applicability,
            )
        )

    def _select_field_candidate(self, key: str, candidates: list[FieldCandidate]) -> FieldCandidate | None:
        if not candidates:
            return None
        rag_candidate = self._candidate_by_source(candidates, "rag_evidence")
        industry_candidate = self._candidate_by_source(candidates, "industry_yaml")
        verified_candidate = self._candidate_by_source(candidates, "verified_search")
        if rag_candidate:
            return rag_candidate
        if key in YAML_PROTECTED_FIELDS and industry_candidate:
            return industry_candidate
        if verified_candidate and self._can_verified_candidate_win(key, verified_candidate, industry_candidate):
            return verified_candidate
        llm_candidate = self._candidate_by_source(candidates, "llm_suggestion")
        if (
            llm_candidate
            and not industry_candidate
            and self._llm_candidate_supported_by_candidates(llm_candidate, candidates)
        ):
            return llm_candidate
        return max(candidates, key=lambda candidate: candidate.match_score)

    @staticmethod
    def _candidate_by_source(candidates: list[FieldCandidate], source_type: str) -> FieldCandidate | None:
        for candidate in candidates:
            if candidate.source_type == source_type:
                return candidate
        return None

    def _can_verified_candidate_win(
        self,
        key: str,
        verified_candidate: FieldCandidate,
        industry_candidate: FieldCandidate | None,
    ) -> bool:
        if key not in SEARCH_OVERRIDABLE_FIELDS:
            return False
        if verified_candidate.match_score < self.config.min_verified_search_score + 55:
            return False
        if not industry_candidate:
            return True
        if self._values_compatible(verified_candidate.value, industry_candidate.value):
            return self._is_more_specific_value(verified_candidate.value, industry_candidate.value)
        if key in REFERENCE_PARAMETER_FIELDS and self._is_better_verified_value(
            key,
            verified_candidate.value,
            industry_candidate.value,
        ):
            return True
        return False

    def _verified_candidate_allowed(self, key: str, value: str, input_fields: dict[str, str]) -> bool:
        if key not in SEARCH_OVERRIDABLE_FIELDS:
            return False
        if not self.config.allow_verified_search_override:
            return False
        if self._score_value_context_match(input_fields, value) < 1 and key not in NUMERIC_SEARCH_OVERRIDE_FIELDS:
            return False
        return True

    def _candidate_match_score(
        self,
        source_type: str,
        key: str,
        value: str,
        process_match: bool,
        material_match: bool,
    ) -> int:
        score = FIELD_CANDIDATE_SOURCE_SCORES.get(source_type, 0)
        if process_match:
            score += 8
        if material_match:
            score += 4
        if key in REFERENCE_PARAMETER_FIELDS and re.search(r"\d", value):
            score += 4
        if source_type == "verified_search" and key in REFERENCE_PARAMETER_FIELDS:
            score += 6
        if source_type == "llm_suggestion":
            score -= 8
        return score

    @staticmethod
    def _candidate_basis(source_type: str) -> str:
        return {
            "rag_evidence": "rag_evidence",
            "industry_yaml": "industry_standard_fields",
            "verified_search": "verified_search_evidence",
            "rule_fallback": "rule_fallback_fields",
            "llm_suggestion": "llm_supported_choice",
        }.get(source_type, source_type)

    @staticmethod
    def _candidate_confidence(source_type: str) -> str:
        return {
            "rag_evidence": "high",
            "industry_yaml": "high",
            "verified_search": "medium",
            "rule_fallback": "low",
            "llm_suggestion": "low",
        }.get(source_type, "low")

    def _llm_value_has_support(
        self,
        key: str,
        value: Any,
        rag_fields: dict[str, str],
        industry_fields: dict[str, str],
        verified_search_fields: dict[str, str],
        rule_fields: dict[str, Any],
    ) -> bool:
        clean_value = self._clean_field_value(key, value)
        if clean_value == "/" or not self._is_short_fill_value(clean_value):
            return False
        support_values = [
            self._clean_document_value(rag_fields.get(key)),
            self._clean_document_value(industry_fields.get(key)),
            self._clean_document_value(verified_search_fields.get(key)),
            self._clean_document_value(rule_fields.get(key)),
        ]
        return any(
            support != "/" and self._values_compatible(clean_value, support)
            for support in support_values
        )

    def _llm_candidate_supported_by_candidates(
        self,
        llm_candidate: FieldCandidate,
        candidates: list[FieldCandidate],
    ) -> bool:
        return any(
            candidate.source_type != "llm_suggestion"
            and self._values_compatible(llm_candidate.value, candidate.value)
            for candidate in candidates
        )

    @staticmethod
    def _is_more_specific_value(left: str, right: str) -> bool:
        left_clean = WeldingStandardAgent._clean_document_value(left)
        right_clean = WeldingStandardAgent._clean_document_value(right)
        if left_clean == "/" or right_clean == "/":
            return False
        if left_clean == right_clean:
            return True
        return len(left_clean) >= len(right_clean)

    def _merge_fields(
        self,
        target: dict[str, str],
        source: dict[str, Any],
        replace_existing: bool,
    ) -> None:
        for key, value in source.items():
            if key not in DOCUMENT_FIELD_KEYS or key in NEVER_SEARCH_OVERRIDE_FIELDS and replace_existing:
                continue
            clean_value = self._clean_field_value(key, value)
            if clean_value == "/":
                continue
            if replace_existing or self._clean_document_value(target.get(key)) == "/":
                target[key] = clean_value

    @staticmethod
    def _filter_rule_fallback_fields(candidate_fields: dict[str, Any]) -> dict[str, Any]:
        allowed_rule_fields = {
            "welding_process",
            "welding_object",
            "joint_type",
            "mechanization",
            "groove_type",
            "base_material",
            "base_material_category",
            "base_material_group",
            "base_material_standard",
            "base_material_grade",
            "base_thickness_or_diameter",
            "base_thickness_range_butt",
            "pipe_diameter_thickness_butt",
            "base_thickness_range_fillet",
            "pipe_diameter_thickness_fillet",
            "corrosion_overlay_chemical_composition",
            "corrosion_overlay_other",
            "joint_other",
        }
        return {
            key: value
            for key, value in candidate_fields.items()
            if key in allowed_rule_fields
        }

    def _filter_llm_fields_for_merge(
        self,
        llm_fields: dict[str, Any],
        industry_fields: dict[str, str],
        verified_search_fields: dict[str, str],
    ) -> dict[str, str]:
        accepted: dict[str, str] = {}
        for key, value in llm_fields.items():
            if key not in DOCUMENT_FIELD_KEYS or key in NEVER_SEARCH_OVERRIDE_FIELDS:
                continue
            clean_value = self._clean_field_value(key, value)
            if clean_value == "/" or not self._is_short_fill_value(clean_value):
                continue
            industry_has_value = self._clean_document_value(industry_fields.get(key)) != "/"
            if not industry_has_value:
                accepted[key] = clean_value
                continue
            verified_value = self._clean_document_value(verified_search_fields.get(key))
            if (
                self.config.allow_verified_search_override
                and key in SEARCH_OVERRIDABLE_FIELDS
                and verified_value != "/"
                and self._values_compatible(clean_value, verified_value)
            ):
                accepted[key] = clean_value
        return accepted

    def _merge_verified_search_fields(
        self,
        target: dict[str, str],
        verified_search_fields: dict[str, str],
        industry_fields: dict[str, str],
    ) -> None:
        for key, value in verified_search_fields.items():
            if key not in SEARCH_OVERRIDABLE_FIELDS or key in NEVER_SEARCH_OVERRIDE_FIELDS:
                continue
            if key in PROCESS_SENSITIVE_FIELDS and not self._field_value_matches_process(target, key, value):
                continue
            clean_value = self._clean_field_value(key, value)
            if clean_value == "/" or not self._is_short_fill_value(clean_value):
                continue
            current_value = self._clean_document_value(target.get(key))
            industry_value = self._clean_document_value(industry_fields.get(key))
            if current_value == "/":
                target[key] = clean_value
                continue
            if industry_value == "/":
                target[key] = clean_value
                continue
            if self._is_better_verified_value(key, clean_value, industry_value):
                target[key] = clean_value

    @staticmethod
    def _is_better_verified_value(key: str, verified_value: str, industry_value: str) -> bool:
        if key in NUMERIC_SEARCH_OVERRIDE_FIELDS:
            return bool(re.search(r"\d", verified_value))
        verified_normalized = verified_value.upper().replace(" ", "")
        industry_normalized = industry_value.upper().replace(" ", "")
        if verified_normalized == industry_normalized:
            return True
        if len(verified_normalized) <= 3 and "/" in industry_value:
            return False
        return len(verified_value) > len(industry_value) and industry_normalized in verified_normalized

    @staticmethod
    def _values_compatible(left: Any, right: Any) -> bool:
        left_text = WeldingStandardAgent._clean_document_value(left).upper().replace(" ", "")
        right_text = WeldingStandardAgent._clean_document_value(right).upper().replace(" ", "")
        if left_text == "/" or right_text == "/":
            return False
        return left_text in right_text or right_text in left_text

    @staticmethod
    def _force_user_input_fields(finalized: dict[str, str], input_fields: dict[str, str]) -> None:
        for source_key, target_key in USER_LOCKED_FIELD_MAP.items():
            value = WeldingStandardAgent._clean_document_value(input_fields.get(source_key))
            if value != "/":
                finalized[target_key] = value

    @staticmethod
    def _force_forbidden_unknown_fields(finalized: dict[str, str]) -> None:
        for key in NEVER_SEARCH_OVERRIDE_FIELDS:
            finalized[key] = "/"

    def _apply_industry_defaults(self, document_fields: dict[str, str]) -> None:
        process = document_fields.get("welding_process", "").upper()
        material = document_fields.get("base_material", "")
        size = document_fields.get("base_thickness_or_diameter", "")

        if "ASTM A106" in material.upper() or "A106" in material.upper():
            self._fill_reference(document_fields, "base_material_category", "P-No.1")
            self._fill_reference(document_fields, "base_material_group", "Group 1")
            self._fill_reference(document_fields, "base_material_standard", "ASTM A106")
            self._fill_reference(document_fields, "base_material_grade", "ASTM A106 Gr.B")
        if "P-NO.1" in material.upper() or "P-NO. 1" in material.upper():
            self._fill_reference(document_fields, "base_material_category", "P-No.1")

        if "对接" in document_fields.get("joint_type", ""):
            self._fill_reference(document_fields, "groove_type", "V形坡口")
        self._fill_reference(document_fields, "backing", "无")
        self._fill_default(document_fields, "joint_other", "/")
        self._fill_reference(document_fields, "base_thickness_range_butt", size)
        self._fill_reference(document_fields, "pipe_diameter_thickness_butt", size)
        self._fill_default(document_fields, "base_thickness_range_fillet", "/")
        self._fill_default(document_fields, "pipe_diameter_thickness_fillet", "/")
        self._fill_default(document_fields, "corrosion_overlay_chemical_composition", "/")
        self._fill_default(document_fields, "corrosion_overlay_other", "/")

        self._apply_process_defaults(document_fields)

        self._fill_reference(document_fields, "butt_weld_position", "5G")
        self._fill_default(document_fields, "fillet_weld_position", "/")
        self._fill_reference(document_fields, "vertical_direction", "向上")
        self._fill_default(document_fields, "pwht_temperature", "/")
        self._fill_default(document_fields, "pwht_time", "/")
        self._fill_reference(document_fields, "preheat_temperature", "≥10℃")
        self._fill_reference(document_fields, "interpass_temperature", "≤250℃")
        self._fill_default(document_fields, "preheat_time", "/")
        self._fill_reference(document_fields, "heating_method", "电加热/火焰加热")
        self._fill_default(document_fields, "heat_input", "/")
        self._fill_default(document_fields, "arc_type", "/")
        self._fill_default(document_fields, "wire_feed_speed", "/")
        self._fill_default(document_fields, "weaving_parameter", "/")
        self._fill_reference(document_fields, "cleaning", CLEANING_DEFAULT)
        self._fill_default(document_fields, "back_gouging", "/")
        self._fill_reference(document_fields, "single_or_multi_pass", "多道焊")
        self._fill_reference(document_fields, "single_or_multi_wire", "单丝/单焊条")
        self._fill_default(document_fields, "contact_tip_distance", "/")
        self._fill_reference(document_fields, "peening", "否")
        self._fill_default(document_fields, "technical_other", "/")
        self._fill_default(document_fields, "prepared_by", "/")
        self._fill_default(document_fields, "prepared_date", "/")
        self._fill_default(document_fields, "reviewed_by", "/")
        self._fill_default(document_fields, "reviewed_date", "/")
        self._fill_default(document_fields, "approved_by", "/")
        self._fill_default(document_fields, "approved_date", "/")

        if self.config.bead_strategy == "root_gtaw_fill_smaw" and "GTAW" in process and "SMAW" in process:
            self._apply_gtaw_smaw_bead_defaults(document_fields)

    def _apply_process_defaults(self, document_fields: dict[str, str]) -> None:
        package_fields = self._default_process_package_fields(document_fields.get("welding_process", ""))
        for key, value in package_fields.items():
            self._fill_reference(document_fields, key, value)

    def _default_process_package_fields(self, process: str) -> dict[str, str]:
        packages = self._builtin_process_reference_packages()
        return dict(packages.get(self._process_package_key(process), {}))

    @staticmethod
    def _fill_default(document_fields: dict[str, str], key: str, value: str) -> None:
        if WeldingStandardAgent._clean_document_value(document_fields.get(key)) == "/":
            document_fields[key] = value

    def _fill_reference(self, document_fields: dict[str, str], key: str, value: str) -> None:
        if self._should_replace_with_reference(document_fields.get(key), value):
            document_fields[key] = value

    def _should_replace_with_reference(self, current_value: Any, reference_value: str) -> bool:
        current = self._clean_document_value(current_value)
        if current == "/":
            return True
        if self.config.reference_fill_mode != "aggressive_reference":
            return False
        normalized = current.upper().replace(" ", "")
        reference_normalized = reference_value.upper().replace(" ", "")
        low_quality_values = {
            "GTAW+SMAW",
            "SMAW+GTAW",
            "AWSA5",
            "AWSA5.",
            "EN",
            "EP",
            "AR",
            "DC",
        }
        if normalized in low_quality_values and normalized != reference_normalized:
            return True
        if "+" in current and "/" in reference_value:
            return True
        if len(current) <= 2 and len(reference_value) > len(current):
            return True
        return False

    @staticmethod
    def _apply_gtaw_smaw_bead_defaults(document_fields: dict[str, str]) -> None:
        bead_defaults = {
            "bead_1_process": "GTAW",
            "bead_1_filler_metal": "ER70S-6",
            "bead_1_diameter": "2.4 mm",
            "bead_1_polarity": "EN",
            "bead_1_current": "80-130",
            "bead_1_voltage": "10-16",
            "bead_1_speed": "50-120",
            "bead_1_heat_input": "/",
            "bead_2_process": "SMAW",
            "bead_2_filler_metal": "E7016",
            "bead_2_diameter": "3.2 mm",
            "bead_2_polarity": "EP",
            "bead_2_current": "90-130",
            "bead_2_voltage": "22-28",
            "bead_2_speed": "80-160",
            "bead_2_heat_input": "/",
        }
        for key, value in bead_defaults.items():
            current = WeldingStandardAgent._clean_document_value(document_fields.get(key))
            if current == "/" or current.upper().replace(" ", "") in {"GTAW+SMAW", "SMAW+GTAW"}:
                document_fields[key] = value

    @classmethod
    def _add_welding_bead_fields(cls, document_fields: dict[str, str]) -> None:
        process_rows = cls._process_bead_rows(document_fields.get("welding_process", ""))
        if process_rows:
            for bead_no in (1, 2):
                row = process_rows[bead_no - 1] if bead_no <= len(process_rows) else {}
                for field_name in ("process", "filler_metal", "diameter", "polarity", "current", "voltage", "speed", "heat_input"):
                    key = f"bead_{bead_no}_{field_name}"
                    if cls._clean_document_value(document_fields.get(key)) == "/":
                        document_fields[key] = row.get(field_name, "/")
            return
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
                key = f"bead_{bead_no}_{field_name}"
                if cls._clean_document_value(document_fields.get(key)) == "/":
                    document_fields[key] = value

    @classmethod
    def _process_bead_rows(cls, process: str) -> list[dict[str, str]]:
        packages = cls._builtin_process_reference_packages()
        key = cls._process_package_key(process)
        rows_by_key = {
            "SMAW": [
                {
                    "process": "SMAW",
                    "filler_metal": "E4315/E5015",
                    "diameter": "3.2 mm",
                    "polarity": "DCEP",
                    "current": "90-150",
                    "voltage": "22-30",
                    "speed": "80-160",
                    "heat_input": "/",
                }
            ],
            "GTAW": [
                {
                    "process": "GTAW",
                    "filler_metal": "ER50-6",
                    "diameter": "2.4 mm",
                    "polarity": "DCEN",
                    "current": "80-130",
                    "voltage": "10-16",
                    "speed": "50-120",
                    "heat_input": "/",
                }
            ],
            "GMAW": [
                {
                    "process": "GMAW",
                    "filler_metal": "ER50-6",
                    "diameter": "1.0/1.2 mm",
                    "polarity": "DCEP",
                    "current": "120-220",
                    "voltage": "18-28",
                    "speed": "180-350",
                    "heat_input": "/",
                }
            ],
            "FCAW": [
                {
                    "process": "FCAW",
                    "filler_metal": "E501T-1",
                    "diameter": "1.2/1.6 mm",
                    "polarity": "DCEP",
                    "current": "140-260",
                    "voltage": "22-32",
                    "speed": "150-320",
                    "heat_input": "/",
                }
            ],
            "SAW": [
                {
                    "process": "SAW",
                    "filler_metal": "H08MnA/H10Mn2",
                    "diameter": "3.2/4.0 mm",
                    "polarity": "DCEP/AC",
                    "current": "350-650",
                    "voltage": "28-36",
                    "speed": "250-550",
                    "heat_input": "/",
                }
            ],
            "GTAW+SMAW": [
                {
                    "process": "GTAW",
                    "filler_metal": "ER50-6",
                    "diameter": "2.4 mm",
                    "polarity": "DCEN",
                    "current": "80-130",
                    "voltage": "10-16",
                    "speed": "50-120",
                    "heat_input": "/",
                },
                {
                    "process": "SMAW",
                    "filler_metal": "E4315/E5015",
                    "diameter": "3.2 mm",
                    "polarity": "DCEP",
                    "current": "90-150",
                    "voltage": "22-30",
                    "speed": "80-160",
                    "heat_input": "/",
                },
            ],
        }
        if key in packages:
            return rows_by_key.get(key, [])
        return []

    @staticmethod
    def _builtin_process_reference_packages() -> dict[str, dict[str, str]]:
        return {
            "SMAW": {
                "mechanization": "手工",
                "filler_category": "焊条",
                "filler_standard": "GB/T 5117 / GB/T 5118",
                "filler_diameter": "3.2 mm",
                "filler_model": "E4315/E5015",
                "filler_trade_name": "E4315/E5015",
                "shielding_gas": "/",
                "shielding_gas_mix": "/",
                "gas_flow": "/",
                "trailing_gas": "/",
                "backing_gas": "/",
                "tungsten_electrode": "/",
                "nozzle_diameter": "/",
                "current_type": "DC",
                "polarity": "DCEP",
                "current": "90-150A",
                "voltage": "22-30V",
                "welding_speed": "80-160 mm/min",
                "weaving": "可摆动",
                "single_or_multi_wire": "单焊条",
            },
            "GTAW": {
                "mechanization": "手工",
                "filler_category": "焊丝",
                "filler_standard": "GB/T 8110",
                "filler_diameter": "2.4 mm",
                "filler_model": "ER50-6",
                "filler_trade_name": "ER50-6",
                "shielding_gas": "Ar",
                "shielding_gas_mix": "99.99%",
                "gas_flow": "8-15 L/min",
                "trailing_gas": "/",
                "backing_gas": "Ar",
                "tungsten_electrode": "铈钨 2.4 mm",
                "nozzle_diameter": "8-12 mm",
                "current_type": "DC",
                "polarity": "DCEN",
                "current": "80-130A",
                "voltage": "10-16V",
                "welding_speed": "50-120 mm/min",
                "weaving": "不摆动",
                "single_or_multi_wire": "单丝",
            },
            "GTAW+SMAW": {
                "mechanization": "手工",
                "filler_category": "焊丝/焊条",
                "filler_standard": "GB/T 8110 / GB/T 5117",
                "filler_diameter": "2.4 mm / 3.2 mm",
                "filler_model": "ER50-6 / E4315",
                "filler_trade_name": "ER50-6 / E4315",
                "shielding_gas": "Ar",
                "shielding_gas_mix": "99.99%",
                "gas_flow": "8-15 L/min",
                "trailing_gas": "/",
                "backing_gas": "Ar",
                "tungsten_electrode": "铈钨 2.4 mm",
                "nozzle_diameter": "8-12 mm",
                "current_type": "DC",
                "polarity": "DCEN/DCEP",
                "current": "GTAW 80-130A / SMAW 90-150A",
                "voltage": "GTAW 10-16V / SMAW 22-30V",
                "welding_speed": "50-160 mm/min",
                "weaving": "GTAW不摆动，SMAW可摆动",
                "single_or_multi_wire": "单丝/单焊条",
            },
            "GMAW": {
                "mechanization": "半自动",
                "filler_category": "实心焊丝",
                "filler_standard": "GB/T 8110",
                "filler_diameter": "1.0 mm / 1.2 mm",
                "filler_model": "ER50-6",
                "filler_trade_name": "ER50-6",
                "shielding_gas": "CO2/Ar+CO2",
                "shielding_gas_mix": "CO2或80%Ar+20%CO2",
                "gas_flow": "15-25 L/min",
                "trailing_gas": "/",
                "backing_gas": "/",
                "tungsten_electrode": "/",
                "nozzle_diameter": "12-16 mm",
                "current_type": "DC",
                "polarity": "DCEP",
                "current": "120-220A",
                "voltage": "18-28V",
                "welding_speed": "180-350 mm/min",
                "arc_type": "短路弧/喷射弧",
                "wire_feed_speed": "/",
                "weaving": "可小幅摆动",
                "single_or_multi_wire": "单丝",
            },
            "FCAW": {
                "mechanization": "半自动",
                "filler_category": "药芯焊丝",
                "filler_standard": "GB/T 10045 / GB/T 17493",
                "filler_diameter": "1.2 mm / 1.6 mm",
                "filler_model": "E501T-1",
                "filler_trade_name": "E501T-1",
                "shielding_gas": "CO2",
                "shielding_gas_mix": "CO2",
                "gas_flow": "15-25 L/min",
                "trailing_gas": "/",
                "backing_gas": "/",
                "tungsten_electrode": "/",
                "nozzle_diameter": "12-16 mm",
                "current_type": "DC",
                "polarity": "DCEP",
                "current": "140-260A",
                "voltage": "22-32V",
                "welding_speed": "150-320 mm/min",
                "arc_type": "/",
                "wire_feed_speed": "/",
                "weaving": "可摆动",
                "single_or_multi_wire": "单丝",
            },
            "SAW": {
                "mechanization": "自动",
                "filler_category": "焊丝/焊剂",
                "filler_standard": "GB/T 5293 / GB/T 12470 / NB/T 47018.4",
                "filler_diameter": "3.2 mm / 4.0 mm",
                "filler_model": "H08MnA/H10Mn2 + HJ431",
                "filler_trade_name": "H08MnA/H10Mn2 + HJ431",
                "shielding_gas": "/",
                "shielding_gas_mix": "/",
                "gas_flow": "/",
                "trailing_gas": "/",
                "backing_gas": "/",
                "tungsten_electrode": "/",
                "nozzle_diameter": "/",
                "current_type": "AC/DC",
                "polarity": "DCEP/AC",
                "current": "350-650A",
                "voltage": "28-36V",
                "welding_speed": "250-550 mm/min",
                "arc_type": "埋弧",
                "wire_feed_speed": "/",
                "weaving": "不摆动",
                "single_or_multi_wire": "单丝",
            },
        }

    @classmethod
    def _enforce_process_consistency(cls, document_fields: dict[str, str]) -> None:
        allowed = set(cls._split_process_terms(document_fields.get("welding_process", "")))
        if not allowed:
            return
        for bead_no in (1, 2):
            key = f"bead_{bead_no}_process"
            bead_process = cls._clean_document_value(document_fields.get(key))
            if bead_process != "/" and bead_process.upper() not in allowed:
                for field_name in ("process", "filler_metal", "diameter", "polarity", "current", "voltage", "speed", "heat_input"):
                    document_fields[f"bead_{bead_no}_{field_name}"] = "/"
        process_key = cls._process_package_key(document_fields.get("welding_process", ""))
        if process_key in {"SMAW", "SAW"}:
            for key in ("shielding_gas", "shielding_gas_mix", "gas_flow", "tungsten_electrode", "nozzle_diameter"):
                document_fields[key] = "/"
        if process_key not in {"GTAW", "GTAW+SMAW"}:
            document_fields["backing_gas"] = "/"
            document_fields["tungsten_electrode"] = "/"

    @classmethod
    def _field_value_matches_process(cls, target: dict[str, str], key: str, value: Any) -> bool:
        process_terms = set(cls._split_process_terms(target.get("welding_process", "")))
        if not process_terms:
            return True
        value_text = cls._clean_document_value(value).upper()
        mentioned_processes = {process for process in SUPPORTED_WELDING_PROCESSES if process in value_text}
        return not mentioned_processes or not mentioned_processes.isdisjoint(process_terms)

    @classmethod
    def _field_value_matches_material(cls, target: dict[str, str], value: Any) -> bool:
        value_text = cls._clean_document_value(value)
        if value_text == "/":
            return False
        material_terms = cls._material_match_terms(target.get("base_material", ""))
        if not material_terms:
            return True
        return cls._any_term_present(value_text, material_terms) or not any(
            cls._contains_term(value_text, term)
            for term in ("ASTM", "ASME", "GB/T", "L245", "L360", "X52", "Q345", "Q355", "20#")
        )

    def _score_value_context_match(self, fields: dict[str, str], value: Any) -> int:
        value_text = self._clean_document_value(value)
        if value_text == "/":
            return 0
        score = 0
        for process in self._split_process_terms(fields.get("welding_process", "")):
            if self._contains_term(value_text, process):
                score += 1
        if self._any_term_present(value_text, self._material_match_terms(fields.get("base_material", ""))):
            score += 2
        if self._contains_term(value_text, fields.get("joint_type", "")):
            score += 1
        if self._contains_term(value_text, fields.get("welding_object", "")):
            score += 1
        return score

    @staticmethod
    def _clean_document_value(value: Any) -> str:
        text = str(value).strip() if value is not None else ""
        lowered = text.lower()
        blocked = ("not found", "unknown tool", "unknown too", "error", "missing")
        if not text or any(item in lowered for item in blocked):
            return "/"
        return text

    @classmethod
    def _clean_field_value(cls, key: str, value: Any) -> str:
        clean_value = cls._clean_document_value(value)
        if key == "cleaning":
            return cls._clean_cleaning_value(clean_value)
        if key in TECHNICAL_FIELD_KEYS and cls._is_unsafe_template_text(clean_value):
            return "/"
        if key in TECHNICAL_FIELD_KEYS and len(clean_value) > 60:
            return clean_value[:60]
        return clean_value

    @classmethod
    def _clean_cleaning_value(cls, value: Any) -> str:
        clean_value = cls._clean_document_value(value)
        if clean_value == "/" or cls._is_unsafe_template_text(clean_value):
            return CLEANING_DEFAULT
        if cls._english_ratio(clean_value) > 0.45:
            return CLEANING_DEFAULT
        if len(clean_value) > 70:
            return CLEANING_DEFAULT
        return clean_value

    @classmethod
    def _is_unsafe_template_text(cls, text: str) -> bool:
        if not text or text == "/":
            return False
        compact = re.sub(r"\s+", "", text).lower()
        if any(marker in compact for marker in ENGLISH_TEMPLATE_MARKERS):
            return True
        if len(compact) > 40 and cls._english_ratio(compact) > 0.7:
            return True
        return False

    @staticmethod
    def _english_ratio(text: str) -> float:
        if not text:
            return 0.0
        letters = sum(1 for char in text if char.isascii() and char.isalpha())
        non_space = sum(1 for char in text if not char.isspace())
        if non_space == 0:
            return 0.0
        return letters / non_space

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
    rag_retriever: Any | None = None,
) -> WeldingStandardAgent:
    return WeldingStandardAgent(search_client=search_client, rag_retriever=rag_retriever)


def build_welding_standard_agent_from_config(config: dict[str, Any]) -> WeldingStandardAgent:
    load_dotenv()
    reference_config = config.get("reference", {})
    mcp_config = config.get("mcp_search", {})
    rag_config = config.get("rag_search", {})

    agent_config = WeldingStandardAgentConfig(
        reference_docx_path=Path(reference_config.get("wps_docx_path", "data/MHPWPS-062.docx")),
        max_reference_chars=int(reference_config.get("max_reference_chars", 4000)),
        max_reference_query_chars=int(reference_config.get("max_reference_query_chars", 1000)),
        llm_enabled=bool(config.get("llm", {}).get("enabled", True)),
        model_config_path=Path(config.get("llm", {}).get("model_config_path", "configs/model_config.yaml")),
        prompt_path=Path(config.get("llm", {}).get("prompt_path", "prompts/welding_standard_agent_prompt.md")),
        max_evidence_chars=int(config.get("llm", {}).get("max_evidence_chars", 9000)),
        max_sources_per_query=int(config.get("llm", {}).get("max_sources_per_query", 3)),
        use_industry_defaults=bool(config.get("generation", {}).get("use_industry_defaults", True)),
        bead_strategy=str(config.get("generation", {}).get("bead_strategy", "root_gtaw_fill_smaw")),
        default_unknown=str(config.get("generation", {}).get("default_unknown", "/")),
        reference_fill_mode=str(config.get("generation", {}).get("reference_fill_mode", "aggressive_reference")),
        industry_standards_path=Path(
            config.get("generation", {}).get(
                "industry_standards_path",
                "configs/welding_industry_standards.yaml",
            )
        ),
        use_industry_standards=bool(config.get("generation", {}).get("use_industry_standards", True)),
        allow_verified_search_override=bool(
            config.get("generation", {}).get("allow_verified_search_override", True)
        ),
        min_evidence_match_score=int(config.get("generation", {}).get("min_evidence_match_score", 3)),
        evidence_decision_mode=str(config.get("generation", {}).get("evidence_decision_mode", "balanced")),
        min_verified_search_score=int(config.get("generation", {}).get("min_verified_search_score", 4)),
        allow_verified_network_refine=bool(
            config.get("generation", {}).get("allow_verified_network_refine", True)
        ),
        conflict_policy=str(
            config.get("generation", {}).get(
                "conflict_policy",
                "prefer_yaml_unless_strong_verified",
            )
        ),
        rag_enabled=bool(rag_config.get("enabled", True)),
        rag_index_dir=Path(rag_config.get("index_dir", "data/rag/faiss")),
        rag_embedding_url=_resolve_env(str(rag_config.get("embedding_url", "http://127.0.0.1:8001/v1/embeddings"))),
        rag_rerank_url=_resolve_env(str(rag_config.get("rerank_url", "http://127.0.0.1:8002/rerank"))),
        rag_embedding_model=str(rag_config.get("embedding_model", "bge-m3")),
        rag_rerank_model=str(rag_config.get("rerank_model", "bge-reranker-v2-m3")),
        rag_semantic_top_k=int(rag_config.get("semantic_top_k", 10)),
        rag_keyword_top_k=int(rag_config.get("keyword_top_k", 10)),
        rag_fusion_top_k=int(rag_config.get("fusion_top_k", 10)),
        rag_final_top_k=int(rag_config.get("final_top_k", 5)),
        rag_rrf_k=int(rag_config.get("rrf_k", 60)),
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
