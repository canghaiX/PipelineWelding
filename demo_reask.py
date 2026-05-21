from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pipeline_welding.agents import build_default_agent


def main() -> None:
    agent = build_default_agent()

    incomplete_case = {
        "welding_process": "SMAW",
        "welding_object": "管道",
        "joint_type": "",
        "base_material": "ASTM A106 Gr.B",
    }

    complete_case = {
        "welding_process": "GTAW+SMAW",
        "welding_object": "管道",
        "joint_type": "对接",
        "base_material": "ASTM A106 Gr.B / P-No.1",
        "base_thickness_or_diameter": "OD 219.1 x 8.2 mm",
    }

    print("=== 信息不完整示例 ===")
    print(agent.next_prompt(incomplete_case))
    print()
    print("=== 信息完整示例 ===")
    print(agent.next_prompt(complete_case))


if __name__ == "__main__":
    main()
