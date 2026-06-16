"""Классификация CSV/Polars ошибок — локальное сопоставление адаптера

Модуль знает о низкоуровневых исключениях Polars и ОС и переводит только
известные отказы в доменный контракт исключений `RowSource`. Неизвестные
исключения не заворачиваются, чтобы `Extractor` мог использовать резервную ветку.

Ответственность:
    - Отличать ошибки чтения CSV-источника от ошибок структурного разбора.
    - Возвращать доменные typed exceptions без знания `ErrorCatalog`.

Вне зоны ответственности:
    - Создание diagnostic-кодов и `DiagnosticItem`.
    - Классификация ошибок других форматов источников.

Известный edge:
    Реальные битые UTF-8 байты (не policy-reject кодировки) Polars поднимает как
    `ComputeError` (⊂ `PolarsError`), поэтому они попадают в `SourceParseError`, а не
    `SourceReadError`. Граница read/parse здесь размыта; надёжно различать их без
    fragile string-matching по тексту исключения нельзя, поэтому это принято осознанно.
"""

from __future__ import annotations

import polars as pl

from connector.domain.ports.transform.source_errors import (
    SourceAdapterError,
    SourceParseError,
    SourceReadError,
)


class PolarsCsvErrorClassifier:
    """Классифицирует известные CSV/Polars исключения в доменные ошибки источника."""

    def classify(self, exc: Exception) -> SourceAdapterError | None:
        """Вернуть типизированную ошибку источника для известного исключения или `None`."""
        if isinstance(exc, (OSError, UnicodeError)):
            return SourceReadError(str(exc))
        if isinstance(exc, pl.exceptions.PolarsError):
            return SourceParseError(str(exc))
        return None
