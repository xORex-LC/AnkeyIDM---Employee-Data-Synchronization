"""Интеграционные тесты Polars CSV source adapter.

Назначение:
    Проверяют adapter на реальном CSV-файле с несколькими Polars-батчами.

Граница тестирования:
    Не запускают downstream pipeline; фокус только на bounded-memory seam
    `PolarsCsvRecordSource -> SourceRecord`.
"""

from __future__ import annotations

import pytest

from connector.infra.sources.csv_reader import PolarsCsvRecordSource


@pytest.mark.integration
def test_polars_csv_record_source_keeps_line_numbers_across_batches(tmp_path) -> None:
    path = tmp_path / "employees.csv"
    rows = ["id;name"]
    rows.extend(f"{idx:03d}; Employee {idx} " for idx in range(1, 26))
    path.write_text("\n".join(rows), encoding="utf-8")

    records = list(
        PolarsCsvRecordSource(
            path,
            has_header=True,
            delimiter=";",
            encoding="utf-8",
            read_batch_size=7,
        )
    )

    assert len(records) == 25
    assert records[0].line_no == 2
    assert records[0].record_id == "line:2"
    assert records[-1].line_no == 26
    assert records[-1].record_id == "line:26"
    assert records[0].values == {"id": "001", "name": "Employee 1"}
    assert records[-1].values == {"id": "025", "name": "Employee 25"}
