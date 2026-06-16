"""Юнит-тесты Polars CSV-адаптера источника.

Назначение:
    Проверяют runtime-паритет extract boundary после миграции CSV-чтения
    со stdlib `csv` на Polars.

Граница тестирования:
    Используют временные CSV-файлы и проверяют только adapter-level контракт
    `SourceRecord`, без downstream-стадий.
"""

from __future__ import annotations

import pytest

from connector.domain.ports.transform.source_errors import (
    SourceParseError,
    SourceReadError,
)
from connector.infra.sources.csv_reader import PolarsCsvRecordSource


@pytest.mark.unit
def test_csv_record_source_uses_declared_delimiter_with_header(tmp_path) -> None:
    path = tmp_path / "employees.csv"
    path.write_text(
        "raw_id;full_name;login\n001;Doe John;jdoe\n",
        encoding="utf-8",
    )

    records = list(
        PolarsCsvRecordSource(
            str(path),
            has_header=True,
            delimiter=";",
            encoding="utf-8",
            read_batch_size=1,
        )
    )

    assert len(records) == 1
    assert records[0].line_no == 2
    assert records[0].values == {
        "raw_id": "001",
        "full_name": "Doe John",
        "login": "jdoe",
    }


@pytest.mark.unit
def test_csv_record_source_uses_declared_delimiter_without_header(tmp_path) -> None:
    path = tmp_path / "employees.csv"
    path.write_text("001;Doe John;jdoe\n", encoding="utf-8")

    records = list(
        PolarsCsvRecordSource(
            str(path),
            has_header=False,
            delimiter=";",
            encoding="utf-8",
            read_batch_size=1,
        )
    )

    assert len(records) == 1
    assert records[0].line_no == 1
    assert records[0].values == {
        "col_0": "001",
        "col_1": "Doe John",
        "col_2": "jdoe",
    }


@pytest.mark.unit
def test_csv_record_source_preserves_strings_and_leading_zeroes(tmp_path) -> None:
    path = tmp_path / "employees.csv"
    path.write_text("id;age\n001;42\n", encoding="utf-8")

    record = next(
        iter(
            PolarsCsvRecordSource(
                str(path),
                has_header=True,
                delimiter=";",
                encoding="utf-8",
            )
        )
    )

    assert record.values == {"id": "001", "age": "42"}
    assert all(isinstance(value, str) for value in record.values.values())


@pytest.mark.unit
def test_csv_record_source_strips_utf8_bom_from_first_header(tmp_path) -> None:
    path = tmp_path / "employees.csv"
    path.write_text("\ufeffТаб.№;name\n001;Ivan\n", encoding="utf-8")

    record = next(
        iter(
            PolarsCsvRecordSource(
                str(path),
                has_header=True,
                delimiter=";",
                encoding="utf-8-sig",
            )
        )
    )

    assert record.values == {"Таб.№": "001", "name": "Ivan"}
    assert "\ufeffТаб.№" not in record.values


@pytest.mark.unit
def test_csv_record_source_matches_trim_and_null_token_parity(tmp_path) -> None:
    path = tmp_path / "employees.csv"
    path.write_text(
        "name;empty;lower_null;upper_null;mixed_null\n  John  ;   ;null;NULL; Null \n",
        encoding="utf-8",
    )

    record = next(
        iter(
            PolarsCsvRecordSource(
                str(path),
                has_header=True,
                delimiter=";",
                encoding="utf-8",
            )
        )
    )

    assert record.values == {
        "name": "John",
        "empty": None,
        "lower_null": None,
        "upper_null": None,
        "mixed_null": None,
    }


@pytest.mark.unit
def test_csv_record_source_preserves_empty_source_rows(tmp_path) -> None:
    path = tmp_path / "employees.csv"
    path.write_text("id;name\n001;A\n\n003;C\n", encoding="utf-8")

    records = list(
        PolarsCsvRecordSource(
            str(path),
            has_header=True,
            delimiter=";",
            encoding="utf-8",
        )
    )

    # Пустая строка не пропускается: эмитится как запись со всеми None,
    # а line_no остаётся выровнен по физической строке CSV.
    assert [(record.line_no, record.values) for record in records] == [
        (2, {"id": "001", "name": "A"}),
        (3, {"id": None, "name": None}),
        (4, {"id": "003", "name": "C"}),
    ]


@pytest.mark.unit
def test_csv_record_source_raises_on_ragged_line(tmp_path) -> None:
    path = tmp_path / "employees.csv"
    path.write_text("id;name\n001;A;EXTRA\n", encoding="utf-8")

    with pytest.raises(SourceParseError):
        list(
            PolarsCsvRecordSource(
                str(path),
                has_header=True,
                delimiter=";",
                encoding="utf-8",
            )
        )


@pytest.mark.unit
def test_csv_record_source_rejects_non_utf8_streaming_encoding(tmp_path) -> None:
    path = tmp_path / "employees.csv"
    path.write_text("id;name\n001;Ivan\n", encoding="utf-8")

    with pytest.raises(SourceReadError, match="supports only utf-8/utf-8-sig"):
        list(
            PolarsCsvRecordSource(
                str(path),
                has_header=True,
                delimiter=";",
                encoding="cp1251",
            )
        )
