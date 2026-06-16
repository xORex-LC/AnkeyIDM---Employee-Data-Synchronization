"""Тесты Extractor — классификация отказов источника

Модуль проверяет доменную boundary-логику Extractor без файловой системы и infra.
Тесты используют `RowSource` в памяти, чтобы фиксировать контракт перехода
от `SourceRecord` к `TransformResult` и diagnostic-кодам.

Ответственность:
    - Проверять pass-through успешных записей extract-потока.
    - Проверять granular diagnostics для типизированных исключений источника.

Вне зоны ответственности:
    - CSV parsing и Polars-исключения.
    - DI wiring source-адаптеров.
"""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from connector.domain.diagnostics.core_catalog import build_core_catalog
from connector.domain.models import DiagnosticStage
from connector.domain.ports.transform.source_errors import SourceParseError, SourceReadError
from connector.domain.transform.core.extractor import Extractor
from connector.domain.transform.core.source_record import SourceRecord

pytestmark = pytest.mark.unit


class _RowsSource:
    """Источник SourceRecord в памяти для unit-проверки Extractor."""

    def __init__(self, records: Iterable[SourceRecord]) -> None:
        self._records = tuple(records)

    def __iter__(self) -> Iterable[SourceRecord]:
        return iter(self._records)


class _FailingSource:
    """Источник, который имитирует stream-level отказ до выдачи записей."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def __iter__(self) -> Iterable[SourceRecord]:
        raise self._exc


def test_extractor_wraps_source_records_without_diagnostics() -> None:
    catalog = build_core_catalog(strict=True)
    record = SourceRecord(line_no=2, record_id="line:2", values={"name": "John"})

    results = list(Extractor(_RowsSource([record]), catalog).run())

    assert len(results) == 1
    result = results[0]
    assert result.record == record
    assert result.row is None
    assert result.row_ref is None
    assert result.match_key is None
    assert result.errors == ()
    assert result.warnings == ()


@pytest.mark.parametrize(
    ("exc", "expected_code"),
    [
        (SourceReadError("cannot read source"), "SOURCE_READ_FAILED"),
        (SourceParseError("cannot parse source"), "SOURCE_PARSE_FAILED"),
        (RuntimeError("unexpected source failure"), "SOURCE_ERROR"),
    ],
)
def test_extractor_classifies_source_stream_failures(exc: Exception, expected_code: str) -> None:
    catalog = build_core_catalog(strict=True)

    results = list(Extractor(_FailingSource(exc), catalog).run())

    assert len(results) == 1
    result = results[0]
    assert result.record == SourceRecord(line_no=0, record_id="source", values={})
    assert result.row is None
    assert result.row_ref is not None
    assert result.row_ref.row_id == "source"
    assert result.errors
    assert result.warnings == ()

    error = result.errors[0]
    assert error.code == expected_code
    assert error.stage is DiagnosticStage.EXTRACT
    assert error.record_ref == result.row_ref
    assert error.message == str(exc)
