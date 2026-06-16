from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any

from dotenv import load_dotenv

from pipeline_welding.agents.welding_reask_agent import REQUIRED_FIELDS, WeldingReaskAgent, build_default_agent
from pipeline_welding.config import load_yaml_config
from pipeline_welding.mcp import McpSearchClient, McpSearchConfig, SearchResult
from pipeline_welding.rag import HybridRagConfig, HybridRagRetriever


FIELD_KEYS = tuple(field.key for field in REQUIRED_FIELDS)
PROCESS_ORDER = ("GTAW", "SMAW", "GMAW", "FCAW", "SAW")
PROCESS_ALIASES: dict[str, tuple[str, ...]] = {
    "SMAW": ("SMAW", "焊条电弧焊", "手工电弧焊", "手弧焊", "manual metal arc", "MMA"),
    "GTAW": ("GTAW", "氩弧焊", "钨极氩弧焊", "钨极气体保护焊", "TIG"),
    "GMAW": ("GMAW", "气保焊", "二保焊", "CO2气体保护焊", "二氧化碳气体保护焊", "熔化极气体保护焊", "MIG", "MAG"),
    "FCAW": ("FCAW", "药芯焊丝电弧焊", "药芯焊丝气保焊"),
    "SAW": ("SAW", "埋弧焊"),
}


@dataclass(frozen=True)
class NaturalLanguageWeldingAgentConfig:
    llm_enabled: bool = True
    model_config_path: Path = Path("configs/model_config.yaml")
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
    mcp_enabled: bool = True
    default_process_for_plate: str = "SMAW"
    max_evidence_chars: int = 6000


class NaturalLanguageWeldingAgent:
    """Converts a plain-language welding need into re-ask required fields."""

    def __init__(
        self,
        config: NaturalLanguageWeldingAgentConfig | None = None,
        reask_agent: WeldingReaskAgent | None = None,
        rag_retriever: Any | None = None,
        search_client: McpSearchClient | None = None,
    ) -> None:
        self.config = config or NaturalLanguageWeldingAgentConfig()
        self.reask_agent = reask_agent or build_default_agent()
        self.rag_retriever = rag_retriever
        self.search_client = search_client

    def analyze(self, description: str) -> dict[str, Any]:
        return asyncio.run(self.analyze_async(description))

    async def analyze_async(self, description: str) -> dict[str, Any]:
        clean_description = description.strip()
        fields = self._extract_explicit_fields(clean_description)
        rag_payload = self._run_rag(clean_description)
        rag_results = self._rag_payload_to_search_results(rag_payload)
        network_results = await self._run_network_search(clean_description, fields)

        evidence_text = self._collect_evidence_text(rag_results, network_results)
        self._merge_missing(fields, self._extract_explicit_fields(evidence_text))
        self._merge_missing(fields, self._infer_fields_from_evidence(clean_description, evidence_text))
        if self.config.llm_enabled:
            self._merge_missing(fields, await self._call_llm(clean_description, fields, rag_results, network_results))
        self._merge_missing(fields, self._default_fields(clean_description, fields, evidence_text))
        self._normalize_welding_process_field(fields)

        inspect_result = self._inspect_required_presence(fields)
        return {
            "fields": {key: fields.get(key, "") for key in FIELD_KEYS if fields.get(key)},
            "complete": inspect_result["complete"],
            "missing_keys": inspect_result["missing_keys"],
            "invalid_keys": inspect_result["invalid_keys"],
            "questions": inspect_result["questions"],
            "rag_evidence": [result.to_dict() for result in rag_results],
            "network_evidence": [result.to_dict() for result in network_results],
        }

    def _extract_explicit_fields(self, text: str) -> dict[str, str]:
        fields = self.reask_agent.extract_fields_from_text(text)
        process = self._extract_process_text(text)
        if process:
            fields["welding_process"] = process
        if self._looks_like_plate(text):
            fields.setdefault("welding_object", "板材")
        if self._looks_like_default_butt_joint(text):
            fields.setdefault("joint_type", "对接")
        material = self._extract_material(text)
        if material:
            fields["base_material"] = material
        thickness = self._extract_plate_thickness(text)
        if thickness:
            fields["base_thickness_or_diameter"] = thickness
        fields = self._normalize_fields(fields)
        self._normalize_welding_process_field(fields)
        return fields

    @staticmethod
    def _extract_process_text(text: str) -> str:
        return NaturalLanguageWeldingAgent.normalize_welding_process(text)

    @staticmethod
    def normalize_welding_process(value: str) -> str:
        if not value:
            return ""
        matched: list[str] = []
        for process in PROCESS_ORDER:
            aliases = PROCESS_ALIASES[process]
            if any(NaturalLanguageWeldingAgent._contains_process_alias(value, alias) for alias in aliases):
                matched.append(process)
        if "GTAW" in matched and "SMAW" in matched:
            return "GTAW+SMAW"
        return matched[0] if matched else ""

    @staticmethod
    def _contains_process_alias(text: str, alias: str) -> bool:
        if not text or not alias:
            return False
        if re.fullmatch(r"[A-Za-z0-9+ -]+", alias):
            return re.search(rf"(?<![A-Za-z0-9]){re.escape(alias)}(?![A-Za-z0-9])", text, flags=re.IGNORECASE) is not None
        return alias.lower() in text.lower()

    @staticmethod
    def _looks_like_plate(text: str) -> bool:
        return any(keyword in text for keyword in ("钢板", "板材", "两块板", "两块", "板")) and "管" not in text

    @staticmethod
    def _looks_like_default_butt_joint(text: str) -> bool:
        if any(keyword in text for keyword in ("角接", "搭接", "支管")):
            return False
        return any(keyword in text for keyword in ("两块", "拼接", "对接", "钢板", "板材"))

    @staticmethod
    def _extract_material(text: str) -> str:
        patterns = (
            r"20\s*(?:号钢|#)",
            r"Q\s*345[RA-Z]?",
            r"Q\s*355[RA-Z]?",
            r"L\s*\d{3}",
            r"ASTM\s*A\d+\s*Gr\.?\s*[A-Z0-9]+",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                value = re.sub(r"\s+", "", match.group(0))
                if re.fullmatch(r"20(?:号钢|#)", value):
                    return "20#"
                return value
        return ""

    @staticmethod
    def _extract_plate_thickness(text: str) -> str:
        patterns = (
            r"(?:板厚|厚度)\s*(\d+(?:\.\d+)?)\s*(?:mm|毫米)?",
            r"(\d+(?:\.\d+)?)\s*(?:mm|毫米)\s*厚",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return f"板厚 {match.group(1)} mm"
        return ""

    def _infer_fields_from_evidence(self, description: str, evidence_text: str) -> dict[str, str]:
        fields: dict[str, str] = {}
        combined = f"{description}\n{evidence_text}"
        process = self.normalize_welding_process(combined)
        if process:
            fields["welding_process"] = process
        fields = self._normalize_fields(fields)
        self._normalize_welding_process_field(fields)
        return fields

    def _default_fields(self, description: str, fields: dict[str, str], evidence_text: str) -> dict[str, str]:
        defaults: dict[str, str] = {}
        if not fields.get("welding_process") and self._looks_like_plate(description):
            defaults["welding_process"] = self.config.default_process_for_plate
        return defaults

    def _run_rag(self, description: str) -> dict[str, Any]:
        if not self.config.rag_enabled or not description:
            return {"query": description, "results": []}
        retriever = self._get_rag_retriever()
        query = f"{description} 焊接工艺 WPS PWPS 焊材 接头 母材 厚度"
        try:
            return retriever.search(query)
        except Exception as exc:
            return {"query": query, "results": [], "error": str(exc)}

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

    @staticmethod
    def _rag_payload_to_search_results(payload: dict[str, Any]) -> list[SearchResult]:
        results: list[SearchResult] = []
        for item in payload.get("results", []):
            if not isinstance(item, dict):
                continue
            chunk = item.get("chunk", {})
            if not isinstance(chunk, dict):
                continue
            title = str(chunk.get("source_file") or "rag_evidence")
            page = chunk.get("page_start")
            section = str(chunk.get("section_title", ""))
            snippet = "\n".join(
                part
                for part in (
                    f"页码: {page}" if page else "",
                    f"章节: {section}" if section else "",
                    str(chunk.get("text", "")),
                )
                if part
            )
            results.append(
                SearchResult(
                    title=title,
                    url=str(chunk.get("source_path", "")),
                    snippet=snippet,
                    raw={"score": item.get("score"), "chunk": chunk},
                )
            )
        return results

    async def _run_network_search(self, description: str, fields: dict[str, str]) -> list[SearchResult]:
        if not self.config.mcp_enabled or self.search_client is None:
            return []
        terms = " ".join(value for value in fields.values() if value)
        query = f"{description} {terms} 焊接工艺 WPS".strip()
        try:
            return await self.search_client.search(query)
        except Exception as exc:
            return [SearchResult(title="", snippet=f"error: {exc}", raw={"error": str(exc)})]

    async def _call_llm(
        self,
        description: str,
        fields: dict[str, str],
        rag_results: list[SearchResult],
        network_results: list[SearchResult],
    ) -> dict[str, str]:
        try:
            from openai import AsyncOpenAI

            model_config = self._load_model_config()
            model = str(model_config.get("model", {}).get("name", "deepseek-chat"))
            temperature = float(model_config.get("model", {}).get("temperature", 0.1))
            max_tokens = int(model_config.get("model", {}).get("max_tokens", 900))
            timeout = float(model_config.get("model", {}).get("timeout_seconds", 60))
            runtime_config = model_config.get("runtime", {})
            api_key_env = str(runtime_config.get("api_key_env", "DEEPSEEK_API_KEY"))
            base_url_env = str(runtime_config.get("base_url_env", "DEEPSEEK_BASE_URL"))
            api_key = os.getenv(api_key_env)
            if not api_key:
                return {}
            client = AsyncOpenAI(api_key=api_key, base_url=os.getenv(base_url_env) or None, timeout=timeout)
            response = await client.chat.completions.create(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": self._llm_system_prompt()},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "description": description,
                                "known_fields": fields,
                                "required_keys": list(FIELD_KEYS),
                                "rag_evidence": self._summarize_results(rag_results),
                                "network_evidence": self._summarize_results(network_results),
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
            )
            return self._parse_llm_fields(response.choices[0].message.content or "{}")
        except Exception:
            return {}

    @staticmethod
    def _llm_system_prompt() -> str:
        return (
            "你负责把非专业中文焊接需求描述转换为 welding_reask_agent 的5个必填字段。"
            "只输出 JSON 对象，字段只能是 welding_process、welding_object、joint_type、base_material、base_thickness_or_diameter。"
            "welding_process 只能输出 SMAW、GTAW、GMAW、FCAW、SAW 或 GTAW+SMAW，禁止输出中文工艺名。"
            "焊条电弧焊/手工电弧焊/手弧焊/MMA 必须返回 SMAW；氩弧焊/钨极氩弧焊/TIG 必须返回 GTAW；"
            "气保焊/二保焊/MIG/MAG 必须返回 GMAW；药芯焊丝电弧焊必须返回 FCAW；埋弧焊必须返回 SAW。"
            "优先使用用户描述中的明确事实，其次使用 RAG 和网络证据。不能确定的字段不要编造。"
            "如果描述是两块钢板且没有接头特殊说明，可推断 welding_object=板材、joint_type=对接。"
        )

    @staticmethod
    def _parse_llm_fields(content: str) -> dict[str, str]:
        data = json.loads(content)
        if not isinstance(data, dict):
            return {}
        fields = data.get("fields", data)
        if not isinstance(fields, dict):
            return {}
        normalized = NaturalLanguageWeldingAgent._normalize_fields(fields)
        NaturalLanguageWeldingAgent._normalize_welding_process_field(normalized)
        return normalized

    def _load_model_config(self) -> dict[str, Any]:
        config_path = self.config.model_config_path
        if not config_path.is_absolute():
            config_path = Path.cwd() / config_path
        return load_yaml_config(config_path)

    def _collect_evidence_text(self, rag_results: list[SearchResult], network_results: list[SearchResult]) -> str:
        parts: list[str] = []
        total = 0
        for result in [*rag_results, *network_results]:
            text = "\n".join(part for part in (result.title, result.snippet) if part)
            if not self._is_clean_text(text):
                continue
            total += len(text)
            if total > self.config.max_evidence_chars:
                break
            parts.append(text)
        return "\n".join(parts)

    @staticmethod
    def _summarize_results(results: list[SearchResult]) -> list[dict[str, str]]:
        return [
            {"title": result.title[:160], "url": result.url[:240], "snippet": result.snippet[:900]}
            for result in results
            if NaturalLanguageWeldingAgent._is_clean_text(result.title) or NaturalLanguageWeldingAgent._is_clean_text(result.snippet)
        ]

    @staticmethod
    def _merge_missing(target: dict[str, str], source: dict[str, str]) -> None:
        for key, value in source.items():
            if key in FIELD_KEYS and value and not target.get(key):
                target[key] = value

    @staticmethod
    def _normalize_fields(fields: dict[str, Any]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key in FIELD_KEYS:
            value = str(fields.get(key, "")).strip()
            if value:
                normalized[key] = value
        return normalized

    @staticmethod
    def _normalize_welding_process_field(fields: dict[str, str]) -> None:
        process = fields.get("welding_process", "")
        normalized = NaturalLanguageWeldingAgent.normalize_welding_process(process)
        if normalized:
            fields["welding_process"] = normalized

    @staticmethod
    def _inspect_required_presence(fields: dict[str, str]) -> dict[str, Any]:
        missing_keys = [key for key in FIELD_KEYS if not str(fields.get(key, "")).strip()]
        questions = [
            field.build_question()
            for field in REQUIRED_FIELDS
            if field.key in missing_keys
        ]
        return {
            "complete": not missing_keys,
            "missing_keys": missing_keys,
            "invalid_keys": [],
            "questions": questions,
        }

    @staticmethod
    def _is_clean_text(text: str) -> bool:
        lowered = text.lower()
        return bool(text.strip()) and not any(item in lowered for item in ("not found", "unknown tool", "error", "missing"))


def build_natural_language_welding_agent(
    search_client: McpSearchClient | None = None,
    rag_retriever: Any | None = None,
    config: NaturalLanguageWeldingAgentConfig | None = None,
) -> NaturalLanguageWeldingAgent:
    return NaturalLanguageWeldingAgent(config=config, rag_retriever=rag_retriever, search_client=search_client)


def build_natural_language_welding_agent_from_config(config: dict[str, Any]) -> NaturalLanguageWeldingAgent:
    load_dotenv()
    llm_config = config.get("llm", {})
    rag_config = config.get("rag_search", {})
    mcp_config = config.get("mcp_search", {})
    generation_config = config.get("generation", {})
    agent_config = NaturalLanguageWeldingAgentConfig(
        llm_enabled=bool(llm_config.get("enabled", True)),
        model_config_path=Path(llm_config.get("model_config_path", "configs/model_config.yaml")),
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
        mcp_enabled=bool(mcp_config.get("enabled", True)),
        default_process_for_plate=str(generation_config.get("default_process_for_plate", "SMAW")),
    )
    search_client = None
    if mcp_config.get("enabled"):
        search_client = McpSearchClient(
            McpSearchConfig(
                transport=_resolve_env(mcp_config.get("transport", "streamable_http")),
                tool_name=_resolve_env(mcp_config.get("tool_name", "tavily_search")),
                command=_resolve_env(mcp_config.get("command", "")),
                args=tuple(_resolve_env(str(item)) for item in mcp_config.get("args", [])),
                url=_resolve_env(mcp_config.get("url", "")),
                max_results=int(mcp_config.get("max_results", 5)),
            )
        )
    return NaturalLanguageWeldingAgent(config=agent_config, search_client=search_client)


def _resolve_env(value: str) -> str:
    pattern = re.compile(r"\$\{([A-Z0-9_]+)\}")

    def replace(match: re.Match[str]) -> str:
        return os.getenv(match.group(1), "")

    return pattern.sub(replace, value)
