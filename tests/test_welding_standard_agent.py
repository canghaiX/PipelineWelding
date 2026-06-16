from pathlib import Path

from pipeline_welding.config import load_yaml_config
from pipeline_welding.agents.welding_standard_agent import (
    DOCUMENT_FIELD_KEYS,
    STANDARD_FIELDS,
    WeldingStandardAgent,
    WeldingStandardAgentConfig,
)
from pipeline_welding.rag import HybridRagConfig
from pipeline_welding.mcp.search_client import SearchResult


FIELDS = {
    "welding_process": "GTAW+SMAW",
    "welding_object": "管道",
    "joint_type": "对接",
    "base_material": "ASTM A106 Gr.B / P-No.1",
    "base_thickness_or_diameter": "OD 219.1 x 8.2 mm",
}


def build_agent() -> WeldingStandardAgent:
    return WeldingStandardAgent(
        config=WeldingStandardAgentConfig(
            llm_enabled=False,
            industry_standards_path=Path("configs/welding_industry_standards.yaml"),
        )
    )


def test_industry_standard_fields_fill_a106_gtaw_smaw_case() -> None:
    agent = build_agent()
    industry_fields = agent._match_industry_standard_fields(FIELDS)

    assert industry_fields["current"] == "GTAW 80-130A / SMAW 90-130A"
    assert industry_fields["voltage"] == "GTAW 10-16V / SMAW 22-28V"
    assert industry_fields["bead_2_polarity"] == "EP"


def test_industry_standards_yaml_has_required_layered_structure() -> None:
    data = load_yaml_config("configs/welding_industry_standards.yaml")

    assert data["metadata"]["scope"]
    assert data["required_input_fields"]
    assert "industrial_pressure_piping" in data["standard_families"]
    assert "oil_gas_pipeline" in data["standard_families"]
    for standard in data["standards"]:
        assert standard["name"]
        assert standard["family"]
        assert standard["match"]
        assert standard["applicable_codes"]
        assert standard["document_fields"]
        for key, field_data in standard["document_fields"].items():
            assert key in DOCUMENT_FIELD_KEYS
            if isinstance(field_data, dict):
                assert "value" in field_data
                assert "basis" in field_data
                assert "confidence" in field_data
                assert "source_codes" in field_data


def test_industry_standards_yaml_has_required_input_field_references() -> None:
    data = load_yaml_config("configs/welding_industry_standards.yaml")
    required_input_fields = data["required_input_fields"]
    fields_by_key = {field["key"]: field for field in required_input_fields}

    assert set(STANDARD_FIELDS).issubset(fields_by_key)
    for key in STANDARD_FIELDS:
        field = fields_by_key[key]
        assert field["label"]
        assert field["type"] in {"enum", "text"}
        assert field["source_hint"]
        assert field["examples"]
        assert field["role"] == "user_constraint"
        assert field["basis"] == "user_input_required"
        assert set(field["used_for"]) == {
            "standard_matching",
            "document_generation",
            "reask_completion",
        }
        if field["type"] == "enum":
            assert field["options"]


def test_industry_standards_yaml_has_all_process_reference_packages() -> None:
    data = load_yaml_config("configs/welding_industry_standards.yaml")
    packages = data["process_reference_packages"]

    for process in ("SMAW", "GTAW", "GTAW+SMAW", "GMAW", "FCAW", "SAW"):
        package = packages[process]
        document_fields = package["document_fields"]
        assert package["applicable_processes"]
        assert document_fields["mechanization"]["value"]
        assert document_fields["filler_category"]["value"]
        assert document_fields["filler_standard"]["value"]
        assert document_fields["current"]["value"]
        assert document_fields["voltage"]["value"]
        assert document_fields["welding_speed"]["value"]
        assert document_fields["bead_1_process"]["value"]


def test_gb_industrial_20_pipe_case_uses_gb_filler_standards() -> None:
    agent = build_agent()
    fields = {
        "welding_process": "GTAW+SMAW",
        "welding_object": "管道",
        "joint_type": "对接",
        "base_material": "20# GB/T 8163",
        "base_thickness_or_diameter": "DN100，壁厚 8 mm",
    }
    industry_fields = agent._match_industry_standard_fields(fields)

    assert industry_fields["base_material_standard"] == "GB/T 8163 / GB/T 9948"
    assert industry_fields["filler_standard"] == "GB/T 8110 / GB/T 5117"
    assert "AWS" not in industry_fields["filler_standard"]
    assert industry_fields["bead_1_filler_metal"] == "ER50-6"


def test_gb_industrial_q345_pipe_case_uses_gb_filler_standards() -> None:
    agent = build_agent()
    fields = {
        "welding_process": "GTAW+SMAW",
        "welding_object": "管道",
        "joint_type": "对接",
        "base_material": "Q345R / 低合金钢",
        "base_thickness_or_diameter": "DN200，壁厚 10 mm",
    }
    industry_fields = agent._match_industry_standard_fields(fields)

    assert industry_fields["base_material_standard"] == "GB/T 1591"
    assert industry_fields["filler_standard"] == "GB/T 8110 / GB/T 5117"
    assert "AWS" not in industry_fields["filler_standard"]
    assert industry_fields["bead_2_filler_metal"] == "E5015"


def test_oil_gas_l360_pipe_case_matches_pipeline_family() -> None:
    agent = build_agent()
    fields = {
        "welding_process": "GTAW+SMAW",
        "welding_object": "管道",
        "joint_type": "对接",
        "base_material": "L360 / X52 管线钢 GB/T 9711",
        "base_thickness_or_diameter": "OD 323.9 x 8.0 mm",
    }
    industry_fields = agent._match_industry_standard_fields(fields)

    assert industry_fields["base_material_standard"] == "GB/T 9711"
    assert industry_fields["base_material_grade"] == "L360/X52"
    assert industry_fields["filler_standard"] == "GB/T 8110 / GB/T 5117"
    assert "AWS" not in industry_fields["filler_standard"]


def test_oil_gas_l245_smaw_pipe_case_matches_pipeline_family() -> None:
    agent = build_agent()
    fields = {
        "welding_process": "SMAW",
        "welding_object": "管道",
        "joint_type": "对接",
        "base_material": "L245 管线钢 GB/T 9711",
        "base_thickness_or_diameter": "OD 219.1 x 6.3 mm",
    }
    industry_fields = agent._match_industry_standard_fields(fields)

    assert industry_fields["base_material_standard"] == "GB/T 9711"
    assert industry_fields["base_material_grade"] == "L245"
    assert industry_fields["filler_standard"] == "GB/T 5117"


def test_unverified_search_does_not_override_industry_standard() -> None:
    agent = build_agent()
    industry_fields = agent._match_industry_standard_fields(FIELDS)
    search_results = {
        "query": [
            SearchResult(
                title="random blog welding tips",
                snippet="ASTM A106 GTAW SMAW current 999-999A voltage 99-99V",
            )
        ]
    }
    rule_fields = agent._build_document_fields(FIELDS, search_results)
    fields = agent._finalize_document_fields(FIELDS, rule_fields, industry_fields, {}, {})

    assert fields["current"] == "GTAW 80-130A / SMAW 90-130A"
    assert fields["voltage"] == "GTAW 10-16V / SMAW 22-28V"
    assert fields["prepared_by"] == "/"


def test_user_input_fields_are_locked_in_final_document_fields() -> None:
    agent = build_agent()
    conflicting_fields = {
        "welding_process": "SMAW",
        "welding_object": "板材",
        "joint_type": "角接",
        "base_material": "Q345",
        "base_thickness_or_diameter": "板厚 30 mm",
    }
    fields = agent._finalize_document_fields(
        FIELDS,
        candidate_fields=conflicting_fields,
        industry_fields=conflicting_fields,
        verified_search_fields=conflicting_fields,
        llm_fields=conflicting_fields,
    )

    for key, value in FIELDS.items():
        assert fields[key] == value


def test_all_supported_processes_generate_process_consistent_fields() -> None:
    expectations = {
        "SMAW": {
            "mechanization": "手工",
            "filler_category": "焊条",
            "bead_1_process": "SMAW",
            "forbidden": ("GTAW", "GMAW", "FCAW", "SAW"),
            "not_applicable": ("shielding_gas", "tungsten_electrode", "nozzle_diameter"),
        },
        "GTAW": {
            "mechanization": "手工",
            "filler_category": "焊丝",
            "bead_1_process": "GTAW",
            "forbidden": ("SMAW", "GMAW", "FCAW", "SAW"),
            "not_applicable": (),
        },
        "GTAW+SMAW": {
            "mechanization": "手工",
            "filler_category": "焊丝/焊条",
            "bead_1_process": "GTAW",
            "bead_2_process": "SMAW",
            "forbidden": ("GMAW", "FCAW", "SAW"),
            "not_applicable": (),
        },
        "GMAW": {
            "mechanization": "半自动",
            "filler_category": "实心焊丝",
            "bead_1_process": "GMAW",
            "forbidden": ("SMAW", "GTAW", "FCAW", "SAW"),
            "not_applicable": ("tungsten_electrode",),
        },
        "FCAW": {
            "mechanization": "半自动",
            "filler_category": "药芯焊丝",
            "bead_1_process": "FCAW",
            "forbidden": ("SMAW", "GTAW", "GMAW", "SAW"),
            "not_applicable": ("tungsten_electrode",),
        },
        "SAW": {
            "mechanization": "自动",
            "filler_category": "焊丝/焊剂",
            "bead_1_process": "SAW",
            "forbidden": ("SMAW", "GTAW", "GMAW", "FCAW"),
            "not_applicable": ("shielding_gas", "gas_flow", "tungsten_electrode", "nozzle_diameter"),
        },
    }

    for process, expected in expectations.items():
        agent = build_agent()
        input_fields = {
            "welding_process": process,
            "welding_object": "管道",
            "joint_type": "对接",
            "base_material": "20# GB/T 8163",
            "base_thickness_or_diameter": "DN100，壁厚 8 mm",
        }
        industry_fields = agent._match_industry_standard_fields(input_fields)
        fields = agent._finalize_document_fields(input_fields, {}, industry_fields, {}, {})

        assert fields["welding_process"] == process
        assert fields["mechanization"] == expected["mechanization"]
        assert fields["filler_category"] == expected["filler_category"]
        assert fields["bead_1_process"] == expected["bead_1_process"]
        if "bead_2_process" in expected:
            assert fields["bead_2_process"] == expected["bead_2_process"]
        else:
            assert fields["bead_2_process"] == "/"
        for field_name in expected["not_applicable"]:
            assert fields[field_name] == "/"
        process_text = " ".join(
            fields[key]
            for key in (
                "current",
                "voltage",
                "filler_standard",
                "filler_model",
                "bead_1_process",
                "bead_2_process",
            )
        )
        for forbidden_process in expected["forbidden"]:
            assert forbidden_process not in process_text


def test_saw_input_does_not_match_gtaw_smaw_industry_standard() -> None:
    agent = build_agent()
    fields = {
        "welding_process": "SAW",
        "welding_object": "管道",
        "joint_type": "对接",
        "base_material": "ASTM A106 Gr.B / P-No.1",
        "base_thickness_or_diameter": "OD 219.1 x 8.2 mm",
    }
    industry_fields = agent._match_industry_standard_fields(fields)
    finalized = agent._finalize_document_fields(fields, {}, industry_fields, {}, {})

    assert finalized["bead_1_process"] == "SAW"
    assert finalized["bead_2_process"] == "/"
    assert "GTAW" not in finalized["current"]
    assert "SMAW" not in finalized["current"]
    assert finalized["shielding_gas"] == "/"
    assert finalized["filler_category"] == "焊丝/焊剂"


def test_verified_search_can_override_numeric_parameters_only() -> None:
    agent = build_agent()
    industry_fields = agent._match_industry_standard_fields(FIELDS)
    search_results = {
        "query": [
            SearchResult(
                title="ASME WPS ASTM A106 Gr.B GTAW SMAW pipe procedure specification",
                snippet=(
                    "ASTM A106 Gr.B P-No.1 pipe butt WPS GTAW SMAW "
                    "焊接电流 70-120A 电压 11-15V 焊接速度 60-150 mm/min"
                ),
            )
        ]
    }
    verified_fields = agent._build_verified_search_fields(FIELDS, search_results)
    fields = agent._finalize_document_fields(FIELDS, {}, industry_fields, verified_fields, {})

    assert fields["current"] == "70-120A"
    assert fields["voltage"] == "11-15V"
    assert fields["polarity"] == "EN/EP"
    assert fields["bead_2_polarity"] == "EP"
    assert fields["welding_process"] == "GTAW+SMAW"


def test_process_mismatched_verified_search_does_not_override_yaml() -> None:
    agent = build_agent()
    fields = {
        "welding_process": "SAW",
        "welding_object": "管道",
        "joint_type": "对接",
        "base_material": "20# GB/T 8163",
        "base_thickness_or_diameter": "DN100，壁厚 8 mm",
    }
    industry_fields = agent._match_industry_standard_fields(fields)
    finalized = agent._finalize_document_fields(
        fields,
        candidate_fields={},
        industry_fields=industry_fields,
        verified_search_fields={
            "current": "GTAW 70-120A / SMAW 90-130A",
            "voltage": "GTAW 11-15V / SMAW 22-28V",
            "bead_1_process": "GTAW",
        },
        llm_fields={},
    )

    assert finalized["current"] == "350-650A"
    assert finalized["voltage"] == "28-36V"
    assert finalized["bead_1_process"] == "SAW"
    assert finalized["bead_2_process"] == "/"


def test_llm_hallucinated_parameter_without_evidence_does_not_override_yaml() -> None:
    agent = build_agent()
    industry_fields = agent._match_industry_standard_fields(FIELDS)
    finalized = agent._finalize_document_fields(
        FIELDS,
        candidate_fields={},
        industry_fields=industry_fields,
        verified_search_fields={},
        llm_fields={
            "current": "999-999A",
            "voltage": "99-99V",
            "prepared_by": "张三",
        },
    )

    assert finalized["current"] == "GTAW 80-130A / SMAW 90-130A"
    assert finalized["voltage"] == "GTAW 10-16V / SMAW 22-28V"
    assert finalized["prepared_by"] == "/"


def test_supported_llm_choice_can_summarize_verified_search_candidate() -> None:
    agent = build_agent()
    industry_fields = agent._match_industry_standard_fields(FIELDS)
    finalized = agent._finalize_document_fields(
        FIELDS,
        candidate_fields={},
        industry_fields=industry_fields,
        verified_search_fields={"current": "70-120A"},
        llm_fields={"current": "70-120A"},
    )

    assert finalized["current"] == "70-120A"


class StubRagRetriever:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str) -> dict:
        self.queries.append(query)
        return {
            "results": [
                {
                    "score": 0.99,
                    "chunk": {
                        "source_file": "GB_T 31032-2023.pdf",
                        "source_path": "docs/GB_T 31032-2023.pdf",
                        "page_start": 12,
                        "page_end": 12,
                        "section_title": "焊接工艺评定基本要素",
                        "text": "ASTM A106 Gr.B P-No.1 管道 GTAW SMAW 预热温度 ≥80℃ 电流 75-115A 电压 12-16V",
                        "metadata": {
                            "table_header": ["焊接工艺评定因素", "要求"],
                            "context_before": ["适用于管道对接焊"],
                            "context_after": ["应按评定合格工艺施焊"],
                        },
                    },
                }
            ]
        }


def test_hybrid_rag_config_defaults_match_required_recall_pipeline() -> None:
    config = HybridRagConfig()

    assert config.semantic_top_k == 10
    assert config.keyword_top_k == 10
    assert config.fusion_top_k == 10
    assert config.rrf_k == 60
    assert config.final_top_k == 5


def test_rag_fields_take_priority_over_network_and_yaml() -> None:
    agent = build_agent()
    industry_fields = agent._match_industry_standard_fields(FIELDS)
    finalized = agent._finalize_document_fields(
        FIELDS,
        candidate_fields={},
        industry_fields=industry_fields,
        verified_search_fields={"current": "70-120A", "preheat_temperature": "≥10℃"},
        llm_fields={},
        rag_fields={"current": "75-115A", "preheat_temperature": "≥80℃"},
    )

    assert finalized["current"] == "75-115A"
    assert finalized["preheat_temperature"] == "≥80℃"


def test_network_and_yaml_fill_when_rag_fields_are_missing() -> None:
    agent = build_agent()
    industry_fields = agent._match_industry_standard_fields(FIELDS)
    finalized = agent._finalize_document_fields(
        FIELDS,
        candidate_fields={},
        industry_fields=industry_fields,
        verified_search_fields={"current": "70-120A"},
        llm_fields={},
        rag_fields={},
    )

    assert finalized["current"] == "70-120A"
    assert finalized["voltage"] == "GTAW 10-16V / SMAW 22-28V"


def test_build_standard_runs_rag_before_network_and_returns_rag_summary() -> None:
    retriever = StubRagRetriever()
    agent = WeldingStandardAgent(
        rag_retriever=retriever,
        config=WeldingStandardAgentConfig(
            llm_enabled=False,
            rag_enabled=True,
            industry_standards_path=Path("configs/welding_industry_standards.yaml"),
        ),
    )

    result = agent.build_standard(FIELDS)

    assert retriever.queries
    assert result["rag_search"][0]["title"].startswith("GB_T 31032-2023.pdf")
    assert result["document_fields"]["current"] == "75-115A"
    assert result["document_fields"]["preheat_temperature"] == "≥80℃"
