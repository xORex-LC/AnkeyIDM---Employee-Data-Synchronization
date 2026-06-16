"""Сборка SourceRecord — формат-агностичный адаптер raw-row

Модуль собирает доменный `SourceRecord` из raw-row, которую произвёл
специализированный reader формата. Он применяет общую null/str-политику и стратегию
идентификатора, не интерпретируя имена полей.

Ответственность:
    - Сохранять физический `line_no`, переданный reader.
    - Нормализовать значения всех raw-row полей.
    - Создавать immutable `SourceRecord` с выбранным `record_id`.

Вне зоны ответственности:
    - Чтение или разбор конкретного формата источника.
    - Проверка наличия колонок, типов и обязательности.
"""

from __future__ import annotations

from collections.abc import Mapping

from connector.domain.transform.core.source_record import SourceRecord
from connector.infra.sources.core.ids import RecordIdStrategy
from connector.infra.sources.core.values import ValueNormalizer


class RecordAssembler:
    """Собирает `SourceRecord` из raw-row без знания формата источника."""

    def __init__(self, *, values: ValueNormalizer, ids: RecordIdStrategy) -> None:
        self._values = values
        self._ids = ids

    def assemble(self, raw_row: Mapping[str, object], *, line_no: int) -> SourceRecord:
        """Собрать `SourceRecord`, сохранив ключи raw-row без валидации схемы."""
        return SourceRecord(
            line_no=line_no,
            record_id=self._ids.record_id(line_no=line_no, raw_row=raw_row),
            values={
                key: self._values.normalize(value) for key, value in raw_row.items()
            },
        )
