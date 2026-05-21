from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
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
