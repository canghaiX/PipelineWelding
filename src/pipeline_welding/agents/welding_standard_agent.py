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


STANDARD_FIELDS = (
    "welding_process",
    "welding_object",
    "joint_type",
    "base_material",
    "base_thickness_or_diameter",
)

DOCUMENT_FIELD_KEYS = (
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
    "pwht_temperature",
    "pwht_time",
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
    "cleaning",
    "back_gouging",
    "single_or_multi_pass",
    "single_or_multi_wire",
    "contact_tip_distance",
    "peening",
    "technical_other",
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
        rule_fields = self._build_document_fields(normalized_input, search_results)
        document_fields = await self._build_document_fields_with_llm(
            normalized_input,
            reference_text,
            search_results,
            rule_fields,
        )

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
            f"{base_terms} 相似 PWPS WPS 焊接工艺规程",
            f"{process} {material} {joint_type} pipe WPS welding procedure specification",
            f"{material} P-No Group ASME IX welding material classification",
            f"{process} {material} {joint_type} filler metal electrode wire AWS",
            f"{process} {material} {size} welding current voltage travel speed heat input",
            f"{material} {size} pipe welding preheat interpass temperature shielding gas",
            f"{process} {joint_type} pipeline welding groove backing cleaning multi pass",
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

    async def _build_document_fields_with_llm(
        self,
        fields: dict[str, str],
        reference_text: str,
        search_results: dict[str, list[SearchResult]],
        fallback_fields: dict[str, str],
    ) -> dict[str, str]:
        if not self.config.llm_enabled:
            return self._finalize_document_fields(fields, fallback_fields)

        try:
            raw_content = await self._call_llm_for_document_fields(
                fields,
                reference_text,
                search_results,
                fallback_fields,
            )
            llm_fields = self._parse_llm_document_fields(raw_content)
        except Exception:
            return self._finalize_document_fields(fields, fallback_fields)

        merged_fields = dict(fallback_fields)
        merged_fields.update(
            {
                key: self._clean_document_value(value)
                for key, value in llm_fields.items()
                if key in DOCUMENT_FIELD_KEYS
            }
        )
        return self._finalize_document_fields(fields, merged_fields)

    async def _call_llm_for_document_fields(
        self,
        fields: dict[str, str],
        reference_text: str,
        search_results: dict[str, list[SearchResult]],
        fallback_fields: dict[str, str],
    ) -> str:
        from openai import AsyncOpenAI

        model_config = self._load_model_config()
        model = str(model_config.get("model", {}).get("name", "gpt-4.1-mini"))
        temperature = float(model_config.get("model", {}).get("temperature", 0.2))
        max_tokens = int(model_config.get("model", {}).get("max_tokens", 1800))
        timeout = float(model_config.get("model", {}).get("timeout_seconds", 60))
        runtime_config = model_config.get("runtime", {})
        api_key_env = str(runtime_config.get("api_key_env", "OPENAI_API_KEY"))
        base_url_env = str(runtime_config.get("base_url_env", "OPENAI_BASE_URL"))
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
                            "search_evidence": self._summarize_search_results(search_results),
                            "rule_fallback_fields": fallback_fields,
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
            "用户输入是约束条件，优先选择相似工艺、相似母材、相似管径/壁厚、相似接头形式的资料；"
            "如果证据不足、冲突或无法可靠确定，字段值填 /；"
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

    def _finalize_document_fields(
        self,
        input_fields: dict[str, str],
        candidate_fields: dict[str, Any],
    ) -> dict[str, str]:
        finalized = {
            key: self._clean_document_value(candidate_fields.get(key))
            for key in DOCUMENT_FIELD_KEYS
        }
        finalized["welding_process"] = self._clean_document_value(input_fields.get("welding_process"))
        finalized["welding_object"] = self._clean_document_value(input_fields.get("welding_object"))
        finalized["joint_type"] = self._clean_document_value(input_fields.get("joint_type"))
        finalized["base_material"] = self._clean_document_value(input_fields.get("base_material"))
        finalized["base_thickness_or_diameter"] = self._clean_document_value(
            input_fields.get("base_thickness_or_diameter")
        )
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
        self._add_welding_bead_fields(finalized)
        return {
            key: self._clean_document_value(finalized.get(key))
            for key in DOCUMENT_FIELD_KEYS
        }

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
                key = f"bead_{bead_no}_{field_name}"
                if WeldingStandardAgent._clean_document_value(document_fields.get(key)) == "/":
                    document_fields[key] = value

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
        llm_enabled=bool(config.get("llm", {}).get("enabled", True)),
        model_config_path=Path(config.get("llm", {}).get("model_config_path", "configs/model_config.yaml")),
        prompt_path=Path(config.get("llm", {}).get("prompt_path", "prompts/welding_standard_agent_prompt.md")),
        max_evidence_chars=int(config.get("llm", {}).get("max_evidence_chars", 9000)),
        max_sources_per_query=int(config.get("llm", {}).get("max_sources_per_query", 3)),
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
