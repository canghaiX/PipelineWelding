from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET


WORD_TEXT_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"


def read_docx_text(path: str | Path) -> str:
    docx_path = Path(path)
    if not docx_path.exists():
        raise FileNotFoundError(f"DOCX reference file not found: {docx_path}")

    with ZipFile(docx_path) as archive:
        xml_bytes = archive.read("word/document.xml")

    root = ET.fromstring(xml_bytes)
    text_parts = [
        element.text.strip()
        for element in root.iter(WORD_TEXT_NAMESPACE)
        if element.text and element.text.strip()
    ]
    return "\n".join(text_parts)
