from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from pipeline_welding.api import app as api_app


DESCRIPTION = "我有两块20mm厚的20号钢板，需要帮我生成一个焊接工艺"


def test_nonprofessional_analyze_endpoint(monkeypatch) -> None:
    def fake_analyze(description: str) -> dict:
        assert description == DESCRIPTION
        return {
            "fields": {
                "welding_process": "SMAW",
                "welding_object": "板材",
                "joint_type": "对接",
                "base_material": "20#",
                "base_thickness_or_diameter": "板厚 20 mm",
            },
            "complete": True,
            "missing_keys": [],
            "invalid_keys": [],
            "questions": [],
            "rag_evidence": [],
            "network_evidence": [],
        }

    monkeypatch.setattr(api_app, "analyze_natural_language_description", fake_analyze)
    client = TestClient(api_app.create_app())

    response = client.post("/api/nonprofessional/analyze", json={"description": DESCRIPTION})

    assert response.status_code == 200
    payload = response.json()
    assert payload["complete"] is True
    assert payload["fields"]["base_material"] == "20#"


def test_nonprofessional_generate_endpoint_returns_download(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "generated.docx"
    output.write_bytes(b"docx")

    monkeypatch.setattr(
        api_app,
        "analyze_natural_language_description",
        lambda description: {
            "fields": {
                "welding_process": "SMAW",
                "welding_object": "板材",
                "joint_type": "对接",
                "base_material": "20#",
                "base_thickness_or_diameter": "板厚 20 mm",
            },
            "complete": True,
            "missing_keys": [],
            "invalid_keys": [],
            "questions": [],
            "rag_evidence": [],
            "network_evidence": [],
        },
    )
    monkeypatch.setattr(api_app, "build_document_from_fields", lambda fields, state: output)
    client = TestClient(api_app.create_app())

    response = client.post("/api/nonprofessional/generate", json={"description": DESCRIPTION})

    assert response.status_code == 200
    payload = response.json()
    assert payload["download_url"].startswith("/api/sessions/")
    assert payload["document_name"] == "generated.docx"


def test_nonprofessional_generate_rejects_incomplete_fields(monkeypatch) -> None:
    monkeypatch.setattr(
        api_app,
        "analyze_natural_language_description",
        lambda description: {
            "fields": {"welding_object": "板材"},
            "complete": False,
            "missing_keys": ["welding_process"],
            "invalid_keys": [],
            "questions": ["请补充焊接工艺"],
            "rag_evidence": [],
            "network_evidence": [],
        },
    )
    client = TestClient(api_app.create_app())

    response = client.post("/api/nonprofessional/generate", json={"description": "帮我生成一个焊接工艺"})

    assert response.status_code == 400
    assert response.json()["detail"]["complete"] is False
