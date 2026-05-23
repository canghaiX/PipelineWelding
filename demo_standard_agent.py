from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pipeline_welding.agents import build_welding_standard_agent_from_config  # noqa: E402
from pipeline_welding.config import load_yaml_config  # noqa: E402


def main() -> None:
    welding_json = {
        "welding_process": "GTAW+SMAW",
        "welding_object": "管道",
        "joint_type": "对接",
        "base_material": "ASTM A106 Gr.B / P-No.1",
        "base_thickness_or_diameter": "OD 219.1 x 8.2 mm",
    }

    config = load_yaml_config(ROOT_DIR / "configs" / "welding_standard_agent_config.yaml")
    agent = build_welding_standard_agent_from_config(config)
    agent.build_standard(welding_json)


if __name__ == "__main__":
    main()
