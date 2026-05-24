from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from pipeline_welding.agents import (  # noqa: E402
    build_welding_document_agent_from_config,
)
from pipeline_welding.config import load_yaml_config  # noqa: E402


def main() -> None:
    config = load_yaml_config(ROOT_DIR / "configs" / "welding_document_agent_config.yaml")
    config["template"]["docx_path"] = str(ROOT_DIR / config["template"]["docx_path"])
    config["output"]["dir"] = str(ROOT_DIR / config["output"]["dir"])
    document_agent = build_welding_document_agent_from_config(config)
    document_agent.build_document(
        {
            "status": "complete",
            "input": {
                "welding_process": "GTAW+SMAW",
                "welding_object": "管道",
                "joint_type": "对接",
                "base_material": "ASTM A106 Gr.B / P-No.1",
                "base_thickness_or_diameter": "OD 219.1 x 8.2 mm",
            },
            "mcp_search": {"results": {}},
            "pipeline_welding_standard": {
                "required_controls": [
                    "焊前确认 WPS/PQR 与母材牌号、规格和接头形式匹配。",
                    "焊接过程中控制电流、电压、热输入和层间温度。",
                ]
            },
        }
    )


if __name__ == "__main__":
    main()
