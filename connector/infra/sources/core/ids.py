"""Идентификаторы записей источника — стратегии record_id для extract

Модуль задаёт узкую точку расширения для формирования `SourceRecord.record_id`.
Дефолтная стратегия остаётся позиционной и не читает бизнес-поля, чтобы
extract-слой не зависел от map-семантики.

Ответственность:
    - Описывать протокол формирования `record_id`.
    - Предоставлять позиционную стратегию `line:{line_no}`.

Вне зоны ответственности:
    - Выбор бизнес-ключа записи.
    - Контентное хэширование или стабильные id по значениям полей.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol


class RecordIdStrategy(Protocol):
    """Стратегия формирования идентификатора исходной записи."""

    def record_id(self, *, line_no: int, raw_row: Mapping[str, object]) -> str:
        """Вернуть record_id для физической строки источника."""
        ...


class PositionalRecordIdStrategy:
    """Позиционная стратегия record_id без доступа к бизнес-семантике строки."""

    def record_id(self, *, line_no: int, raw_row: Mapping[str, object]) -> str:
        """Вернуть `line:{line_no}` для совместимости текущего extract-контракта."""
        return f"line:{line_no}"
