from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from pipeline_welding.agents import (
    REQUIRED_FIELDS,
    build_default_agent,
    build_welding_document_agent_from_config,
    build_welding_standard_agent_from_config,
)
from pipeline_welding.config import load_yaml_config
from pipeline_welding.graphs import (
    MAX_REASK_ROUNDS,
    build_welding_reask_graph,
    create_initial_state,
)
from pipeline_welding.graphs.welding_reask_graph import build_round_message


ROOT_DIR = Path(__file__).resolve().parents[3]


class MessageRequest(BaseModel):
    message: str = Field(..., min_length=1)


class DirectFieldsRequest(BaseModel):
    fields: dict[str, str] = Field(default_factory=dict)


class GenerateRequest(BaseModel):
    fields: dict[str, str] | None = None


def create_app() -> FastAPI:
    app = FastAPI(title="Pipeline Welding API")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    graph = build_welding_reask_graph()
    sessions: dict[str, dict[str, Any]] = {}

    def get_session(session_id: str) -> dict[str, Any]:
        session = sessions.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return session

    def session_payload(session_id: str) -> dict[str, Any]:
        session = get_session(session_id)
        state = session["state"]
        return {
            "session_id": session_id,
            "state": state,
            "download_url": session.get("download_url"),
            "document_name": session.get("document_name"),
        }

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/required-fields")
    def required_fields() -> dict[str, Any]:
        return {
            "fields": [
                {
                    "key": field.key,
                    "label": field.label,
                    "source_hint": field.source_hint,
                    "field_type": field.field_type.value,
                    "options": list(field.options),
                    "examples": list(field.examples),
                }
                for field in REQUIRED_FIELDS
            ]
        }

    @app.post("/api/sessions")
    def create_session() -> dict[str, Any]:
        session_id = uuid4().hex
        sessions[session_id] = {"state": create_initial_state()}
        return session_payload(session_id)

    @app.post("/api/sessions/{session_id}/message")
    def send_message(session_id: str, request: MessageRequest) -> dict[str, Any]:
        session = get_session(session_id)
        state = dict(session["state"])
        if state.get("round_count", 0) >= MAX_REASK_ROUNDS and not state.get("complete"):
            raise HTTPException(status_code=400, detail="Maximum re-ask rounds reached")

        state["latest_user_input"] = request.message.strip()
        session["state"] = graph.invoke(state)
        session.pop("download_url", None)
        session.pop("document_name", None)
        session.pop("document_path", None)
        return session_payload(session_id)

    @app.post("/api/sessions/{session_id}/fields")
    def update_fields(session_id: str, request: DirectFieldsRequest) -> dict[str, Any]:
        session = get_session(session_id)
        state = dict(session["state"])
        fields = dict(state.get("fields", {}))
        fields.update({key: value.strip() for key, value in request.fields.items()})
        result = build_default_agent().inspect(fields)
        message = build_round_message(result, state)
        state["fields"] = fields
        state["latest_user_input"] = ""
        state["complete"] = result["complete"]
        state["missing_keys"] = result["missing_keys"]
        state["invalid_keys"] = result["invalid_keys"]
        state["questions"] = result["questions"]
        state["assistant_message"] = message
        session["state"] = state
        session.pop("download_url", None)
        session.pop("document_name", None)
        session.pop("document_path", None)
        return session_payload(session_id)

    @app.post("/api/sessions/{session_id}/generate")
    async def generate_document(session_id: str, request: GenerateRequest) -> dict[str, Any]:
        session = get_session(session_id)
        state = dict(session["state"])
        fields = request.fields or state.get("fields", {})
        if not isinstance(fields, dict) or not fields:
            raise HTTPException(status_code=400, detail="No welding fields available")

        document_path = await run_in_threadpool(build_document_from_fields, fields, state)
        session["document_path"] = str(document_path)
        session["document_name"] = document_path.name
        session["download_url"] = f"/api/sessions/{session_id}/download"
        return session_payload(session_id)

    @app.get("/api/sessions/{session_id}/download")
    def download_document(session_id: str) -> FileResponse:
        session = get_session(session_id)
        document_path = Path(str(session.get("document_path", "")))
        if not document_path.exists() or not document_path.is_file():
            raise HTTPException(status_code=404, detail="Generated document not found")
        return FileResponse(
            path=document_path,
            filename=document_path.name,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    return app


def build_document_from_fields(fields: dict[str, Any], state: dict[str, Any]) -> Path:
    standard_config = load_yaml_config(ROOT_DIR / "configs" / "welding_standard_agent_config.yaml")
    standard_agent = build_welding_standard_agent_from_config(standard_config)
    standard_result = standard_agent.build_standard(
        {
            "fields": fields,
            "reask_complete": state.get("complete", False),
            "missing_keys": state.get("missing_keys", []),
            "round_count": state.get("round_count", 0),
        }
    )

    document_config = load_yaml_config(ROOT_DIR / "configs" / "welding_document_agent_config.yaml")
    document_config["template"]["docx_path"] = str(ROOT_DIR / document_config["template"]["docx_path"])
    document_config["output"]["dir"] = str(ROOT_DIR / document_config["output"]["dir"])
    document_agent = build_welding_document_agent_from_config(document_config)
    return document_agent.build_document(standard_result)


app = create_app()
