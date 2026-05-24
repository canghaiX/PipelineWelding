from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pipeline_welding.agents import (  # noqa: E402
    build_welding_document_agent_from_config,
    build_welding_standard_agent_from_config,
)
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
    standard_result = agent.build_standard(welding_json)

    document_config = load_yaml_config(ROOT_DIR / "configs" / "welding_document_agent_config.yaml")
    document_config["template"]["docx_path"] = str(ROOT_DIR / document_config["template"]["docx_path"])
    document_config["output"]["dir"] = str(ROOT_DIR / document_config["output"]["dir"])
    document_agent = build_welding_document_agent_from_config(document_config)
    document_agent.build_document(standard_result)


if __name__ == "__main__":
    main()
