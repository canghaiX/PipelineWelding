from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any


class FieldType(str, Enum):
    ENUM = "enum"
    TEXT = "text"
    NUMBER = "number"


@dataclass(frozen=True)
class RequiredField:
    key: str
    label: str
    source_hint: str
    field_type: FieldType
    options: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()

    def build_question(self) -> str:
        option_text = f" 可选值：{' / '.join(self.options)}。" if self.options else ""
        example_text = f" 示例：{'、'.join(self.examples)}。" if self.examples else ""
        return (
            f"请补充【{self.label}】。"
            f"建议来源：{self.source_hint}。"
            f"{option_text}{example_text}"
        )


REQUIRED_FIELDS: tuple[RequiredField, ...] = (
    RequiredField(
        key="welding_process",
        label="焊接工艺",
        source_hint="WPS/PQR、工艺卡或施工方案",
        field_type=FieldType.ENUM,
        options=("SMAW", "GTAW", "GMAW", "FCAW", "SAW"),
        examples=("SMAW", "GTAW+SMAW"),
    ),
    RequiredField(
        key="welding_object",
        label="焊接对象",
        source_hint="图纸、工单或检验委托单",
        field_type=FieldType.ENUM,
        options=("管道", "板材", "管件", "设备"),
        examples=("管道", "设备"),
    ),
    RequiredField(
        key="joint_type",
        label="接头形式",
        source_hint="焊接接头详图、坡口图或施工图",
        field_type=FieldType.ENUM,
        options=("对接", "角接", "搭接", "支管连接"),
        examples=("对接", "支管连接"),
    ),
    RequiredField(
        key="base_material",
        label="母材牌号/规格",
        source_hint="材料数据库、标准材料分组、材质证明书或设计文件",
        field_type=FieldType.TEXT,
        examples=("20#", "Q345R", "ASTM A106 Gr.B / P-No.1"),
    ),
    RequiredField(
        key="base_thickness_or_diameter",
        label="母材厚度/管径",
        source_hint="图纸、材料清单、标准适用范围",
        field_type=FieldType.TEXT,
        examples=("壁厚 8 mm，DN100", "板厚 12 mm", "OD 219.1 x 8.2 mm"),
    ),
)


class WeldingReaskAgent:
    """Checks welding context completeness and asks targeted follow-up questions."""

    def __init__(self, required_fields: tuple[RequiredField, ...] = REQUIRED_FIELDS) -> None:
        self.required_fields = required_fields

    def inspect(self, payload: dict[str, Any]) -> dict[str, Any]:
        missing_fields = [
            field
            for field in self.required_fields
            if self._is_missing(payload.get(field.key))
        ]
        invalid_fields = [
            self._invalid_enum_result(field, payload.get(field.key))
            for field in self.required_fields
            if field.field_type == FieldType.ENUM and not self._is_missing(payload.get(field.key))
        ]
        invalid_fields = [item for item in invalid_fields if item is not None]

        questions = [field.build_question() for field in missing_fields]
        questions.extend(item["question"] for item in invalid_fields)

        return {
            "complete": not missing_fields and not invalid_fields,
            "missing_keys": [field.key for field in missing_fields],
            "invalid_keys": [item["key"] for item in invalid_fields],
            "questions": questions,
            "message": self._build_message(questions),
        }

    def next_prompt(self, payload: dict[str, Any]) -> str:
        return self.inspect(payload)["message"]

    def extract_fields_from_text(self, text: str) -> dict[str, str]:
        extracted: dict[str, str] = {}
        source = text.strip()
        if not source:
            return extracted

        process_values = self._extract_processes(source)
        if process_values:
            extracted["welding_process"] = "+".join(process_values)

        object_value = self._first_keyword(source, ("管道", "板材", "管件", "设备"))
        if object_value:
            extracted["welding_object"] = object_value

        joint_value = self._first_keyword(source, ("支管连接", "对接", "角接", "搭接"))
        if joint_value:
            extracted["joint_type"] = joint_value

        material_value = self._extract_value_after_label(
            source, ("母材牌号/规格", "母材牌号", "母材规格", "母材", "材质", "材料")
        )
        if material_value:
            extracted["base_material"] = material_value

        size_value = self._extract_size(source)
        if size_value:
            extracted["base_thickness_or_diameter"] = size_value

        return extracted

    @staticmethod
    def _is_missing(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, (list, tuple, set, dict)):
            return len(value) == 0
        return False

    @staticmethod
    def _normalize(value: Any) -> str:
        return str(value).strip().upper()

    def _invalid_enum_result(
        self, field: RequiredField, value: Any
    ) -> dict[str, str] | None:
        if not field.options:
            return None

        normalized_options = {self._normalize(option) for option in field.options}
        submitted_values = self._split_multi_value(value)
        if all(self._normalize(item) in normalized_options for item in submitted_values):
            return None

        return {
            "key": field.key,
            "question": (
                f"【{field.label}】当前填写为“{value}”，不在支持范围内。"
                f"请从 {' / '.join(field.options)} 中选择，或确认是否需要扩展选项。"
            ),
        }

    @staticmethod
    def _split_multi_value(value: Any) -> list[str]:
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]

        text = str(value).strip()
        for separator in ("+", "＋", "/", "、", ",", "，"):
            text = text.replace(separator, "|")
        return [item.strip() for item in text.split("|") if item.strip()]

    def _extract_processes(self, text: str) -> list[str]:
        normalized_text = text.upper()
        found: list[tuple[int, str]] = []
        for process in self._field_options("welding_process"):
            position = normalized_text.find(process)
            if position >= 0:
                found.append((position, process))
        return [process for _, process in sorted(found)]

    @staticmethod
    def _first_keyword(text: str, keywords: tuple[str, ...]) -> str | None:
        for keyword in keywords:
            if keyword in text:
                return keyword
        return None

    @staticmethod
    def _extract_value_after_label(text: str, labels: tuple[str, ...]) -> str | None:
        label_pattern = "|".join(re.escape(label) for label in labels)
        pattern = rf"(?:{label_pattern})\s*[:：为是]?\s*([^,，;；。\n]+)"
        match = re.search(pattern, text)
        if not match:
            return None
        value = match.group(1).strip()
        return value or None

    @staticmethod
    def _extract_size(text: str) -> str | None:
        value = WeldingReaskAgent._extract_value_after_label(
            text, ("母材厚度/管径", "厚度/管径", "母材厚度", "管径", "壁厚", "板厚", "规格")
        )
        if value:
            return value

        patterns = (
            r"(?:DN|dn)\s*\d+(?:\.\d+)?",
            r"(?:OD|od)\s*\d+(?:\.\d+)?(?:\s*[xX*]\s*\d+(?:\.\d+)?)?",
            r"(?:壁厚|板厚|厚度)\s*\d+(?:\.\d+)?\s*(?:mm|毫米)?",
            r"\d+(?:\.\d+)?\s*(?:mm|毫米)",
        )
        matches = []
        for pattern in patterns:
            matches.extend(match.group(0).strip() for match in re.finditer(pattern, text))
        return "，".join(dict.fromkeys(matches)) if matches else None

    def _field_options(self, key: str) -> tuple[str, ...]:
        for field in self.required_fields:
            if field.key == key:
                return field.options
        return ()

    @staticmethod
    def _build_message(questions: list[str]) -> str:
        if not questions:
            return "焊接缺陷分析所需的关键工艺信息已完整，可以继续进行缺陷判断。"

        numbered_questions = "\n".join(
            f"{index}. {question}" for index, question in enumerate(questions, start=1)
        )
        return (
            "当前信息不足，暂不能可靠判断焊接缺陷原因。"
            "请先补充以下关键工艺信息：\n"
            f"{numbered_questions}"
        )


def build_default_agent() -> WeldingReaskAgent:
    return WeldingReaskAgent()
