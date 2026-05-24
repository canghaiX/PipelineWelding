from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pipeline_welding.graphs import (  # noqa: E402
    MAX_REASK_ROUNDS,
    build_welding_reask_graph,
    create_initial_state,
)
from pipeline_welding.agents import build_welding_standard_agent_from_config  # noqa: E402
from pipeline_welding.config import load_yaml_config  # noqa: E402


def main() -> None:
    graph = build_welding_reask_graph()
    state = create_initial_state()

    print("焊接缺陷重问智能体已启动。")
    print("请像正常对话一样描述焊接信息。输入 exit 或 quit 可退出。")
    print("示例：工艺 GTAW+SMAW，焊接对象是管道，接头对接，母材 ASTM A106 Gr.B，OD 219.1 x 8.2 mm")
    print()

    while state.get("round_count", 0) < MAX_REASK_ROUNDS:
        user_input = input(f"用户 第 {state.get('round_count', 0) + 1} 轮> ").strip()
        if user_input.lower() in {"exit", "quit"}:
            print("已退出。")
            return
        if not user_input:
            print("请输入焊接工艺、对象、接头、母材或厚度/管径等信息。")
            continue

        state["latest_user_input"] = user_input
        state = graph.invoke(state)

        print()
        print("Agent>")
        print(state["assistant_message"])
        print()

        if state.get("complete") or state.get("round_count", 0) >= MAX_REASK_ROUNDS:
            run_welding_standard_agent(state)
            return

    return


def run_welding_standard_agent(state: dict) -> None:
    print("正在将当前焊接 JSON 信息传递给标准制定智能体，并执行 MCP 查询...")
    print()

    config = load_yaml_config(ROOT_DIR / "configs" / "welding_standard_agent_config.yaml")
    standard_agent = build_welding_standard_agent_from_config(config)
    standard_agent.build_standard(
        {
            "fields": state.get("fields", {}),
            "reask_complete": state.get("complete", False),
            "missing_keys": state.get("missing_keys", []),
            "round_count": state.get("round_count", 0),
        }
    )


if __name__ == "__main__":
    main()
