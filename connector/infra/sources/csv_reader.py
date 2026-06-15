"""Адаптер CSV-источника для extract-стадии на Polars.

Назначение:
    Читает CSV-файл батчами и выдаёт поток `SourceRecord` без знания о датасете
    и downstream-стадиях.

Граница ответственности:
    Модуль владеет только file I/O, CSV-парсингом, null-нормализацией,
    сохранением строкового контракта значений и сборщиком текущего
    CSV-адаптера. Выбор адаптера выполняет `SourceAdapterRegistry` в
    composition root.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator, Literal

import polars as pl

from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform_dsl import resolve_source_location
from connector.domain.transform_dsl.specs import SourceSpec

_UTF8_ENCODINGS = {"utf8", "utf-8", "utf8-sig", "utf-8-sig"}


class PolarsCsvRecordSource:
    """CSV-источник поверх `polars.scan_csv().collect_batches()`.

    Назначение:
        Преобразует строки CSV-файла в `SourceRecord` с сохранением текущей
        семантики номера строки, идентификатора записи, headerless-имён колонок
        и null-нормализации.

    Контракт:
        - все non-null значения остаются строками;
        - первая колонка не содержит UTF-8 BOM;
        - `record_id` и `line_no` сохраняют прежнюю позиционную семантику.
    """

    def __init__(
        self,
        path: str | Path,
        has_header: bool,
        *,
        delimiter: str = ",",
        encoding: str = "utf-8-sig",
        read_batch_size: int = 10_000,
    ) -> None:
        self.path = str(Path(path))
        self.has_header = has_header
        self.delimiter = delimiter
        self.encoding = encoding
        self.read_batch_size = read_batch_size

    def __iter__(self) -> Iterator[SourceRecord]:
        """Итерировать CSV как поток `SourceRecord`.

        Инварианты:
            - header-файл начинает data line с 2, headerless-файл — с 1;
            - `record_id` всегда совпадает с физической строкой CSV;
            - пустые строки источника не пропускаются (эмитятся как запись со
              всеми `None`), сохраняя выравнивание `line_no` по физической строке;
            - значения нормализуются до `str | None` на границе источника.
        """
        row_no = 2 if self.has_header else 1
        for batch in self._iter_batches():
            batch = self._normalize_columns(batch)
            for row in batch.iter_rows(named=True):
                yield SourceRecord(
                    line_no=row_no,
                    record_id=f"line:{row_no}",
                    values={key: _normalize_value(value) for key, value in row.items()},
                )
                row_no += 1

    def _iter_batches(self) -> Iterator[pl.DataFrame]:
        """Итерировать Polars-батчи без полной материализации файла.

        Использует `scan_csv().collect_batches()` (не deprecated
        `read_csv_batched`). Пустые строки источника **не пропускаются**:
        Polars отдаёт их как строку со всеми `None`, и они сохраняются как
        полноценная запись с корректным физическим `line_no`.
        """
        frame = pl.scan_csv(
            self.path,
            has_header=self.has_header,
            separator=self.delimiter,
            infer_schema_length=0,
            encoding=_normalize_encoding(self.encoding),
            try_parse_dates=False,
            truncate_ragged_lines=False,
        )
        yield from frame.collect_batches(chunk_size=self.read_batch_size)

    def _normalize_columns(self, batch: pl.DataFrame) -> pl.DataFrame:
        """Нормализовать имена колонок после чтения Polars.

        Контракт:
            Header-режим удаляет UTF-8 BOM только из первой колонки.
            Headerless-режим переводит имена Polars `column_n` в текущий
            контракт `col_{i}`.
        """
        if self.has_header:
            columns = list(batch.columns)
            if columns:
                columns[0] = columns[0].lstrip("\ufeff")
            return batch.rename(dict(zip(batch.columns, columns, strict=True)))
        return batch.rename(
            {column: f"col_{idx}" for idx, column in enumerate(batch.columns)}
        )


def build_csv_source(
    spec: SourceSpec,
    *,
    read_batch_size: int = 10_000,
) -> PolarsCsvRecordSource:
    """Построить текущий CSV `RowSource` из декларации `SourceSpec`.

    Контракт:
        - поддерживается только `type=file`, `format.kind=csv`;
        - path resolution принадлежит builder'у, а не `DatasetSpec`;
        - параметры времени выполнения передаются через замыкание регистрации
          сборщика в `SourceContainer`.
    """
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


def _normalize_value(value: Any) -> str | None:
    """Нормализовать значение CSV к контракту `str | None`."""
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() == "null":
        return None
    return text


def _normalize_encoding(encoding: str) -> Literal["utf8"]:
    """Сузить DSL encoding до поддержанного streaming-режима Polars."""
    normalized = encoding.strip().lower().replace("_", "-")
    if normalized not in _UTF8_ENCODINGS:
        raise ValueError(
            "Polars CSV streaming currently supports only utf-8/utf-8-sig encodings"
        )
    return "utf8"
