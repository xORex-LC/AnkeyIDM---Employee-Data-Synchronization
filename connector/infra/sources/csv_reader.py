"""Совместимость CSV reader — переходный re-export нового CSV-пакета

Модуль сохраняет старый импорт `connector.infra.sources.csv_reader` на время
поэтапной декомпозиции DEC-003. Реальная реализация находится в
`connector.infra.sources.csv`.

Ответственность:
    - Экспортировать `PolarsCsvRecordSource` для существующих точек вызова.
    - Экспортировать `build_csv_source` для текущей DI-регистрации.

Вне зоны ответственности:
    - Содержать runtime-логику чтения CSV.
    - Быть постоянным API совместимости после cleanup-этапа.
"""

from connector.infra.sources.csv.builder import build_csv_source
from connector.infra.sources.csv.record_source import PolarsCsvRecordSource

__all__ = [
    "PolarsCsvRecordSource",
    "build_csv_source",
]
