"""Тесты PolarsCsvErrorClassifier — сопоставление типизированных ошибок источника

Модуль проверяет только локальную для адаптера классификацию низкоуровневых CSV/Polars
исключений. Он не создаёт diagnostics и не запускает `Extractor`.

Ответственность:
    - Проверять сопоставление известных ошибок чтения.
    - Проверять сопоставление известных ошибок структурного разбора.
    - Проверять отсутствие принудительного заворачивания неизвестных исключений.

Вне зоны ответственности:
    - Проверка `ErrorCatalog` и diagnostic-кодов.
    - Реальное чтение CSV-файлов.
"""

from __future__ import annotations

import polars as pl
import pytest

from connector.domain.ports.transform.source_errors import (
    SourceParseError,
    SourceReadError,
)
from connector.infra.sources.csv.errors import PolarsCsvErrorClassifier

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "exc",
    [
        OSError("cannot open file"),
        UnicodeError("cannot decode"),
    ],
)
def test_classifier_maps_read_failures_to_source_read_error(exc: Exception) -> None:
    classifier = PolarsCsvErrorClassifier()

    typed = classifier.classify(exc)

    assert isinstance(typed, SourceReadError)
    assert str(typed) == str(exc)


@pytest.mark.parametrize(
    "exc",
    [
        pl.exceptions.ComputeError("bad csv row"),
        pl.exceptions.NoDataError("empty source"),
    ],
)
def test_classifier_maps_polars_failures_to_source_parse_error(exc: Exception) -> None:
    classifier = PolarsCsvErrorClassifier()

    typed = classifier.classify(exc)

    assert isinstance(typed, SourceParseError)
    assert str(typed) == str(exc)


def test_classifier_does_not_wrap_unknown_exceptions() -> None:
    classifier = PolarsCsvErrorClassifier()

    assert classifier.classify(RuntimeError("unexpected")) is None
