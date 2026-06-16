"""Источник CSV-записей — композиция reader и сборщика ядра источников

Модуль реализует `RowSource` для CSV через двух сотрудников: специализированный
`PolarsCsvFrameReader` производит raw-row, а формат-агностичный
`RecordAssembler` собирает доменный `SourceRecord`.

Ответственность:
    - Соединять CSV reader и сборщик ядра источников.
    - Сохранять внешний контракт `PolarsCsvRecordSource`.
    - Отдавать ленивый поток `SourceRecord`.

Вне зоны ответственности:
    - Разбор CSV и классификация Polars-ошибок.
    - Null/str политика и формирование record_id.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from connector.domain.transform.core.source_record import SourceRecord
from connector.infra.sources.core import (
    PositionalRecordIdStrategy,
    RecordAssembler,
    ValueNormalizer,
)
from connector.infra.sources.csv.reader import PolarsCsvFrameReader


class PolarsCsvRecordSource:
    """CSV `RowSource` поверх `PolarsCsvFrameReader` и `RecordAssembler`."""

    def __init__(
        self,
        path: str | Path,
        has_header: bool,
        *,
        delimiter: str = ",",
        encoding: str = "utf-8-sig",
        read_batch_size: int = 10_000,
        reader: PolarsCsvFrameReader | None = None,
        assembler: RecordAssembler | None = None,
    ) -> None:
        self.path = str(Path(path))
        self.has_header = has_header
        self.delimiter = delimiter
        self.encoding = encoding
        self.read_batch_size = read_batch_size
        self._reader = reader or PolarsCsvFrameReader(
            self.path,
            self.has_header,
            delimiter=self.delimiter,
            encoding=self.encoding,
            read_batch_size=self.read_batch_size,
        )
        self._assembler = assembler or RecordAssembler(
            values=ValueNormalizer(),
            ids=PositionalRecordIdStrategy(),
        )

    def __iter__(self) -> Iterator[SourceRecord]:
        """Итерировать CSV как поток `SourceRecord` с прежним extract-контрактом."""
        for line_no, raw_row in self._reader.iter_rows():
            yield self._assembler.assemble(raw_row, line_no=line_no)
