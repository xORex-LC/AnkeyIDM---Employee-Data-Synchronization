"""Сборщик CSV-источника — сборка RowSource из SourceSpec

Модуль содержит точку композиции для CSV-адаптера: проверяет поддерживаемую
комбинацию `type=file` + `format.kind=csv`, резолвит location и создаёт
`PolarsCsvRecordSource`.

Ответственность:
    - Сохранять контракт `SourceSpec -> RowSource` для реестра.
    - Выполнять path resolution через transform DSL helper.
    - Передавать runtime-параметры чтения в CSV-адаптер.

Вне зоны ответственности:
    - Чтение CSV-файла.
    - Валидация содержимого строк источника.
"""

from __future__ import annotations

from connector.domain.transform_dsl import resolve_source_location
from connector.domain.transform_dsl.specs import SourceSpec
from connector.infra.sources.csv.record_source import PolarsCsvRecordSource


def build_csv_source(
    spec: SourceSpec,
    *,
    read_batch_size: int = 10_000,
) -> PolarsCsvRecordSource:
    """Построить CSV `RowSource` из декларации `SourceSpec`."""
    source_format = spec.source.format
    if spec.source.type != "file" or source_format.kind != "csv":
        raise ValueError(
            f"{spec.dataset} source spec must be file/csv for current CSV adapter"
        )
    source_path = resolve_source_location(spec)
    return PolarsCsvRecordSource(
        source_path,
        source_format.has_header,
        delimiter=source_format.delimiter,
        encoding=source_format.encoding,
        read_batch_size=read_batch_size,
    )
