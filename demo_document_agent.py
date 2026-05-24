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
            "document_fields": {
                "unit_name": "/",
                "wps_no": "PWPS-TEST",
                "pqr_no": "PQR-TEST",
                "welding_process": "GTAW+SMAW",
                "mechanization": "手工",
                "welding_object": "管道",
                "groove_type": "对接",
                "backing": "/",
                "joint_other": "/",
                "base_material": "ASTM A106 Gr.B",
                "base_material_category": "P-No.1",
                "base_material_group": "Group 1",
                "base_material_standard": "ASTM A106",
                "base_material_grade": "Gr.B",
                "base_thickness_or_diameter": "OD 219.1 x 8.2 mm",
                "base_thickness_range_butt": "8.2 mm",
                "base_thickness_range_fillet": "/",
                "pipe_diameter_thickness_butt": "OD 219.1 x 8.2 mm",
                "pipe_diameter_thickness_fillet": "/",
                "corrosion_overlay_chemical_composition": "/",
                "corrosion_overlay_other": "/",
                "filler_category": "焊丝",
                "filler_standard": "AWS A5.18",
                "filler_diameter": "2.4mm",
                "filler_model": "ER70S-6",
                "filler_trade_name": "ER70S-6",
                "filler_class": "/",
                "butt_weld_position": "5G",
                "fillet_weld_position": "/",
                "vertical_direction": "向上",
                "pwht_temperature": "/",
                "pwht_time": "/",
                "preheat_temperature": "≥10℃",
                "interpass_temperature": "≤150℃",
                "preheat_time": "/",
                "heating_method": "电加热/火焰加热",
                "shielding_gas": "Ar",
                "shielding_gas_mix": "99.99%",
                "gas_flow": "10-15L/min",
                "trailing_gas": "/",
                "backing_gas": "/",
                "current_type": "DC",
                "polarity": "EN",
                "current": "100-160A",
                "voltage": "19-25V",
                "welding_speed": "55-150mm/min",
                "heat_input": "10",
                "tungsten_electrode": "铈钨 2.4 mm",
                "nozzle_diameter": "8-12 mm",
                "arc_type": "/",
                "wire_feed_speed": "/",
                "weaving": "摆动焊",
                "weaving_parameter": "/",
                "cleaning": "Cleaning(Brushing,Grinding,etc.)MethodofBackGougingTungstenElectrodeSizeandTypePOSTWELDHEATTREATMENT(QW-407)GAS(QW-408)",
                "back_gouging": "/",
                "single_or_multi_pass": "多道焊",
                "single_or_multi_wire": "单丝",
                "contact_tip_distance": "/",
                "peening": "否",
                "technical_other": "/",
                "prepared_by": "/",
                "prepared_date": "/",
                "reviewed_by": "/",
                "reviewed_date": "/",
                "approved_by": "/",
                "approved_date": "/",
                "bead_1_process": "GTAW",
                "bead_1_filler_metal": "ER70S-6",
                "bead_1_diameter": "2.4 mm",
                "bead_1_polarity": "EN",
                "bead_1_current": "80-130",
                "bead_1_voltage": "10-16",
                "bead_1_speed": "50-120",
                "bead_1_heat_input": "/",
                "bead_2_process": "SMAW",
                "bead_2_filler_metal": "E7016",
                "bead_2_diameter": "3.2 mm",
                "bead_2_polarity": "EP",
                "bead_2_current": "90-130",
                "bead_2_voltage": "22-28",
                "bead_2_speed": "80-160",
                "bead_2_heat_input": "/",
            },
        }
    )


if __name__ == "__main__":
    main()
