from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

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
    """Builds a JSON welding standard draft from re-ask JSON, MCP search, and WPS reference."""

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
        validation = self._validate_input(normalized_input)
        reference_text = self._load_reference_text()
        search_queries = self._build_search_queries(normalized_input, reference_text)
        search_results = await self._run_search(search_queries)

        return {
            "status": "complete" if validation["complete"] else "incomplete",
            "input": normalized_input,
            "missing_keys": validation["missing_keys"],
            "reference": {
                "file": str(self.config.reference_docx_path),
                "available": bool(reference_text),
                "excerpt": reference_text[: self.config.max_reference_chars],
            },
            "mcp_search": {
                "enabled": self.search_client is not None,
                "queries": search_queries,
                "results": {
                    query: [result.to_dict() for result in results]
                    for query, results in search_results.items()
                },
            },
            "pipeline_welding_standard": self._draft_standard(
                normalized_input,
                reference_text,
                search_results,
                self.config.reference_docx_path,
            ),
        }

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
        wps_terms = self._compact_reference_for_query(reference_text)

        base_terms = " ".join(term for term in (process, material, size, joint_type, welding_object) if term)
        return [
            f"{base_terms} 管道焊接 标准 WPS {wps_terms}",
            f"{process} {material} {joint_type} 焊接工艺评定 标准 {wps_terms}",
            f"{material} {size} 管道 焊接 参数 预热 层间温度 {wps_terms}",
        ]

    def _compact_reference_for_query(self, reference_text: str) -> str:
        compacted = " ".join(reference_text.split())
        return compacted[: self.config.max_reference_query_chars]

    async def _run_search(self, queries: list[str]) -> dict[str, list[SearchResult]]:
        if self.search_client is None:
            return {query: [] for query in queries}

        results: dict[str, list[SearchResult]] = {}
        for query in queries:
            results[query] = await self.search_client.search(query)
        return results

    @staticmethod
    def _draft_standard(
        fields: dict[str, str],
        reference_text: str,
        search_results: dict[str, list[SearchResult]],
        reference_docx_path: Path,
    ) -> dict[str, Any]:
        evidence_titles = [
            result.title
            for results in search_results.values()
            for result in results
            if result.title
        ]
        return {
            "standard_name": "管道焊接工艺标准草案",
            "applicable_scope": {
                "welding_object": fields.get("welding_object", ""),
                "joint_type": fields.get("joint_type", ""),
                "base_material": fields.get("base_material", ""),
                "base_thickness_or_diameter": fields.get("base_thickness_or_diameter", ""),
            },
            "welding_process": fields.get("welding_process", ""),
            "reference_basis": {
                "local_wps": str(reference_docx_path) if reference_text else "",
                "mcp_search_evidence": evidence_titles,
            },
            "required_controls": [
                "焊接前确认 WPS/PQR 与母材牌号、规格、厚度/管径和接头形式匹配。",
                "焊前检查坡口、组对间隙、错边量、清洁度和定位焊质量。",
                "按工艺文件控制焊接电流、电压、焊接速度、热输入、预热温度和层间温度。",
                "多层多道焊时，每道焊后清理熔渣、飞溅，并检查裂纹、未熔合、气孔等缺陷。",
                "焊后按项目标准执行外观检查、无损检测和必要的热处理记录。",
            ],
            "acceptance_output": {
                "format": "json",
                "must_include": list(STANDARD_FIELDS),
            },
            "notes": [
                "该标准为基于输入 JSON、本地 WPS 文档和 MCP 搜索结果生成的草案。",
                "正式发布前应由焊接责任工程师按适用法规、设计文件和业主标准复核。",
            ],
        }


def build_welding_standard_agent(
    search_client: McpSearchClient | None = None,
) -> WeldingStandardAgent:
    return WeldingStandardAgent(search_client=search_client)


def build_welding_standard_agent_from_config(config: dict[str, Any]) -> WeldingStandardAgent:
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
                transport=mcp_config.get("transport", "stdio"),
                tool_name=mcp_config.get("tool_name", "search"),
                command=mcp_config.get("command", ""),
                args=tuple(mcp_config.get("args", [])),
                url=mcp_config.get("url", ""),
                max_results=int(mcp_config.get("max_results", 5)),
            )
        )

    return WeldingStandardAgent(search_client=search_client, config=agent_config)
