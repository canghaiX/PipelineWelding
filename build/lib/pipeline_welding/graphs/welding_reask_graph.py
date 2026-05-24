from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from pipeline_welding.agents import build_default_agent


MAX_REASK_ROUNDS = 5


class WeldingReaskState(TypedDict, total=False):
    latest_user_input: str
    messages: list[dict[str, str]]
    fields: dict[str, str]
    round_count: int
    complete: bool
    missing_keys: list[str]
    invalid_keys: list[str]
    questions: list[str]
    assistant_message: str


def create_initial_state() -> WeldingReaskState:
    return {
        "latest_user_input": "",
        "messages": [],
        "fields": {},
        "round_count": 0,
        "complete": False,
        "missing_keys": [],
        "invalid_keys": [],
        "questions": [],
        "assistant_message": "",
    }


def merge_user_input(state: WeldingReaskState) -> WeldingReaskState:
    agent = build_default_agent()
    latest_user_input = state.get("latest_user_input", "")
    fields = dict(state.get("fields", {}))
    extracted_fields = agent.extract_fields_from_text(latest_user_input)

    for key, value in extracted_fields.items():
        if value:
            fields[key] = value

    messages = list(state.get("messages", []))
    if latest_user_input:
        messages.append({"role": "user", "content": latest_user_input})

    return {
        **state,
        "fields": fields,
        "messages": messages,
        "round_count": state.get("round_count", 0) + 1,
    }


def inspect_state(state: WeldingReaskState) -> WeldingReaskState:
    agent = build_default_agent()
    result = agent.inspect(state.get("fields", {}))
    message = build_round_message(result, state)

    messages = list(state.get("messages", []))
    messages.append({"role": "assistant", "content": message})

    return {
        **state,
        "complete": result["complete"],
        "missing_keys": result["missing_keys"],
        "invalid_keys": result["invalid_keys"],
        "questions": result["questions"],
        "assistant_message": message,
        "messages": messages,
    }


def build_round_message(result: dict[str, Any], state: WeldingReaskState) -> str:
    if result["complete"]:
        return "信息完整，可以继续进行缺陷判断。\n" + format_complete_case(
            state.get("fields", {})
        )

    if state.get("round_count", 0) >= MAX_REASK_ROUNDS:
        return (
            "已达到 5 轮问答上限，信息仍不完整。\n"
            "当前已提取的信息如下：\n"
            + format_complete_case(state.get("fields", {}))
            + "\n仍需补充：\n"
            + "\n".join(f"{index}. {question}" for index, question in enumerate(result["questions"], 1))
        )

    return "信息不完整，请补充以下信息：\n" + "\n".join(
        f"{index}. {question}" for index, question in enumerate(result["questions"], 1)
    )


def format_complete_case(fields: dict[str, str]) -> str:
    ordered_keys = (
        "welding_process",
        "welding_object",
        "joint_type",
        "base_material",
        "base_thickness_or_diameter",
    )
    lines = ["complete_case = {"]
    for key in ordered_keys:
        value = fields.get(key, "")
        lines.append(f'    "{key}": "{value}",')
    lines.append("}")
    return "\n".join(lines)


def build_welding_reask_graph():
    graph = StateGraph(WeldingReaskState)
    graph.add_node("merge_user_input", merge_user_input)
    graph.add_node("inspect_state", inspect_state)

    graph.set_entry_point("merge_user_input")
    graph.add_edge("merge_user_input", "inspect_state")
    graph.add_edge("inspect_state", END)
    return graph.compile()
