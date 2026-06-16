from pipeline_welding.agents.welding_document_agent import WeldingDocumentAgent


def test_single_process_keeps_second_bead_row_empty() -> None:
    fields = WeldingDocumentAgent._ensure_required_document_fields(
        {
            "welding_process": "SAW",
            "filler_trade_name": "H08MnA/H10Mn2 + HJ431",
            "filler_diameter": "3.2 mm / 4.0 mm",
            "polarity": "DCEP/AC",
            "current": "350-650A",
            "voltage": "28-36V",
            "welding_speed": "250-550 mm/min",
            "bead_1_process": "SAW",
        }
    )

    assert fields["bead_1_process"] == "SAW"
    assert fields["bead_2_process"] == "/"
    assert fields["bead_2_filler_metal"] == "/"
    assert fields["bead_2_current"] == "/"


def test_combined_process_keeps_second_bead_row() -> None:
    fields = WeldingDocumentAgent._ensure_required_document_fields(
        {
            "welding_process": "GTAW+SMAW",
            "bead_1_process": "GTAW",
            "bead_2_process": "SMAW",
            "bead_2_filler_metal": "E4315",
        }
    )

    assert fields["bead_1_process"] == "GTAW"
    assert fields["bead_2_process"] == "SMAW"
    assert fields["bead_2_filler_metal"] == "E4315"
