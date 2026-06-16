"""Ядро адаптеров источников — формат-агностичная сборка SourceRecord

Пакет содержит переиспользуемые сотрудники для адаптеров источников,
которые уже получили сырую строку данных из конкретного backend. Эти
сотрудники фиксируют общий extract-boundary контракт `str | None`.

Ответственность:
    - Нормализовать значения источника к общему контракту.
    - Формировать record_id без знания бизнес-полей.
    - Собирать доменный `SourceRecord` из raw-row и физического номера строки.

Вне зоны ответственности:
    - Чтение файлов, БД, HTTP или других внешних источников.
    - Разбор CSV/JSON/SQL-курсоров и классификация low-level ошибок.
    - Валидация схемы, типов и обязательности полей.
"""

from connector.infra.sources.core.assembler import RecordAssembler
from connector.infra.sources.core.ids import (
    PositionalRecordIdStrategy,
    RecordIdStrategy,
)
from connector.infra.sources.core.values import ValueNormalizer

__all__ = [
    "PositionalRecordIdStrategy",
    "RecordAssembler",
    "RecordIdStrategy",
    "ValueNormalizer",
]
