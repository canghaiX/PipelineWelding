from __future__ import annotations

from pathlib import Path

from pipeline_welding.agents.natural_language_welding_agent import (
    NaturalLanguageWeldingAgent,
    NaturalLanguageWeldingAgentConfig,
)
from pipeline_welding.mcp.search_client import SearchResult


DESCRIPTION = "我有两块20mm厚的20号钢板，需要帮我生成一个焊接工艺"


class StubRagRetriever:
    def __init__(self, text: str = "") -> None:
        self.text = text
        self.queries: list[str] = []

    def search(self, query: str) -> dict:
        self.queries.append(query)
        if not self.text:
            return {"query": query, "results": []}
        return {
            "query": query,
            "results": [
                {
                    "score": 0.9,
                    "chunk": {
                        "source_file": "常用焊材汇总.pdf",
                        "source_path": "docs/常用焊材汇总.pdf",
                        "page_start": 1,
                        "page_end": 1,
                        "section_title": "焊接材料",
                        "text": self.text,
                        "metadata": {},
                    },
                }
            ],
        }


class StubSearchClient:
    async def search(self, query: str) -> list[SearchResult]:
        return [SearchResult(title="SMAW WPS", snippet="20# 钢板 对接 SMAW 焊接工艺")]


class LlmStubAgent(NaturalLanguageWeldingAgent):
    async def _call_llm(self, description, fields, rag_results, network_results):
        return {"welding_process": "焊条电弧焊"}


def build_agent(rag_text: str = "", mcp_enabled: bool = False) -> NaturalLanguageWeldingAgent:
    return NaturalLanguageWeldingAgent(
        config=NaturalLanguageWeldingAgentConfig(
            llm_enabled=False,
            rag_enabled=True,
            mcp_enabled=mcp_enabled,
            default_process_for_plate="SMAW",
        ),
        rag_retriever=StubRagRetriever(rag_text),
        search_client=StubSearchClient() if mcp_enabled else None,
    )


def test_plain_description_extracts_plate_material_joint_and_thickness() -> None:
    result = build_agent().analyze(DESCRIPTION)

    assert result["fields"]["welding_object"] == "板材"
    assert result["fields"]["joint_type"] == "对接"
    assert result["fields"]["base_material"] == "20#"
    assert result["fields"]["base_thickness_or_diameter"] == "板厚 20 mm"


def test_rag_or_tavily_evidence_can_fill_process() -> None:
    result = build_agent("20# 钢板 对接 SMAW 焊接工艺").analyze(DESCRIPTION)

    assert result["fields"]["welding_process"] == "SMAW"
    assert result["complete"] is True


def test_rule_default_fills_process_when_evidence_missing_for_plate() -> None:
    result = build_agent().analyze(DESCRIPTION)

    assert result["fields"]["welding_process"] == "SMAW"
    assert result["complete"] is True


def test_nonprofessional_mode_normalizes_process_text_to_standard_code() -> None:
    result = build_agent().analyze("我有两块20mm厚的20号钢板，想用焊条电弧焊生成焊接工艺")

    assert result["fields"]["welding_process"] == "SMAW"
    assert result["complete"] is True
    assert result["invalid_keys"] == []


def test_process_aliases_are_normalized_to_standard_codes() -> None:
    cases = {
        "焊条电弧焊": "SMAW",
        "手工电弧焊": "SMAW",
        "手弧焊": "SMAW",
        "manual metal arc": "SMAW",
        "MMA": "SMAW",
        "氩弧焊": "GTAW",
        "钨极氩弧焊": "GTAW",
        "TIG": "GTAW",
        "气保焊": "GMAW",
        "二保焊": "GMAW",
        "MIG": "GMAW",
        "MAG": "GMAW",
        "药芯焊丝电弧焊": "FCAW",
        "埋弧焊": "SAW",
        "氩弧焊打底，焊条电弧焊填充": "GTAW+SMAW",
    }

    for alias, expected in cases.items():
        assert NaturalLanguageWeldingAgent.normalize_welding_process(alias) == expected


def test_llm_process_alias_is_normalized_before_return() -> None:
    agent = LlmStubAgent(
        config=NaturalLanguageWeldingAgentConfig(
            llm_enabled=True,
            rag_enabled=False,
            mcp_enabled=False,
        ),
        rag_retriever=StubRagRetriever(),
    )

    result = agent.analyze("我有两块20mm厚的20号钢板，需要帮我生成一个焊接工艺")

    assert result["fields"]["welding_process"] == "SMAW"


def test_incomplete_description_returns_reask_questions() -> None:
    result = build_agent().analyze("帮我生成一个焊接工艺")

    assert result["complete"] is False
    assert "base_material" in result["missing_keys"]
    assert result["questions"]


def test_config_path_type_is_path() -> None:
    config = NaturalLanguageWeldingAgentConfig(model_config_path=Path("configs/model_config.yaml"))

    assert config.model_config_path.name == "model_config.yaml"
