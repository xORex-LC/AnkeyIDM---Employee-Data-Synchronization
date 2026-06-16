"""Тесты ядра источников — формат-агностичная сборка SourceRecord

Модуль проверяет сотрудников `infra.sources.core` без файловой системы, Polars и
CSV-специфики. Тесты фиксируют общий extract-boundary контракт, который
переиспользуют CSV и будущие source-адаптеры.

Ответственность:
    - Проверять паритет null/str нормализатора.
    - Проверять позиционный `record_id`.
    - Проверять сборку `SourceRecord` без schema-валидации.

Вне зоны ответственности:
    - CSV parsing, header/headerless и BOM-политика.
    - Классификация ошибок конкретных backend.
"""

from __future__ import annotations

import pytest

from connector.infra.sources.core import (
    PositionalRecordIdStrategy,
    RecordAssembler,
    ValueNormalizer,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("null", None),
        ("NULL", None),
        (" Null ", None),
        ("  John  ", "John"),
        ("0", "0"),
        ("False", "False"),
        (42, "42"),
    ],
)
def test_value_normalizer_matches_extract_null_and_string_contract(
    raw_value: object,
    expected: str | None,
) -> None:
    normalizer = ValueNormalizer()

    assert normalizer.normalize(raw_value) == expected


def test_positional_record_id_strategy_uses_physical_line_number() -> None:
    strategy = PositionalRecordIdStrategy()

    assert strategy.record_id(line_no=17, raw_row={"id": "ignored"}) == "line:17"


def test_record_assembler_preserves_line_id_keys_and_normalizes_values() -> None:
    assembler = RecordAssembler(
        values=ValueNormalizer(),
        ids=PositionalRecordIdStrategy(),
    )
    raw_row = {
        "id": " 001 ",
        "name": "  John  ",
        "empty": "",
        "null_token": "NULL",
        "flag": "False",
    }

    record = assembler.assemble(raw_row, line_no=9)

    assert record.line_no == 9
    assert record.record_id == "line:9"
    assert record.values == {
        "id": "001",
        "name": "John",
        "empty": None,
        "null_token": None,
        "flag": "False",
    }


def test_record_assembler_does_not_validate_fields_or_csv_headers() -> None:
    assembler = RecordAssembler(
        values=ValueNormalizer(),
        ids=PositionalRecordIdStrategy(),
    )

    record = assembler.assemble({"unexpected": " value "}, line_no=1)

    assert record.values == {"unexpected": "value"}
