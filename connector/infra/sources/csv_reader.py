"""Адаптер CSV-источника для extract-стадии.

Назначение:
    Читает CSV-файл и выдаёт поток `SourceRecord` без знания о датасете и
    downstream-стадиях.

Граница ответственности:
    Модуль владеет только file I/O, CSV-парсингом, null-нормализацией и
    сборщиком текущего CSV-адаптера. Выбор адаптера выполняет
    `SourceAdapterRegistry` в composition root.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterator

from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform_dsl import resolve_source_location
from connector.domain.transform_dsl.specs import SourceSpec
from connector.infra.sources.csv_utils import CsvFormatError, parse_null


class CsvRecordSource:
    """Универсальный CSV-источник поверх stdlib `csv`.

    Назначение:
        Преобразует строки CSV-файла в `SourceRecord` с сохранением текущей
        семантики номера строки, идентификатора записи и null-нормализации.

    Граница ответственности:
        Не выбирает источник по DSL и не создаёт `TransformResult`; этим
        занимаются source registry и `Extractor`.
    """

    def __init__(
        self,
        path: str | Path,
        has_header: bool,
        *,
        delimiter: str = ",",
        encoding: str = "utf-8-sig",
    ) -> None:
        self.path = str(Path(path))
        self.has_header = has_header
        self.delimiter = delimiter
        self.encoding = encoding

    def __iter__(self) -> Iterator[SourceRecord]:
        with open(self.path, "r", encoding=self.encoding, newline="") as f:
            if self.has_header:
                dict_reader = csv.DictReader(f, delimiter=self.delimiter)
                if dict_reader.fieldnames is None:
                    raise CsvFormatError("Missing header in source CSV")
                for csv_line_no, row in enumerate(dict_reader, start=2):
                    if not row:
                        continue
                    if None in row:
                        extra = row.get(None) or []
                        got = len(dict_reader.fieldnames) + len(extra)
                        raise CsvFormatError(
                            f"Invalid column count at line {csv_line_no}: expected {len(dict_reader.fieldnames)}, got {got}"
                        )
                    values = {key: parse_null(row.get(key)) for key in row}
                    record = SourceRecord(
                        line_no=csv_line_no,
                        record_id=f"line:{csv_line_no}",
                        values=values,
                    )
                    yield record
                return

            plain_reader = csv.reader(f, delimiter=self.delimiter)
            expected_len: int | None = None
            for csv_line_no, plain_row in enumerate(plain_reader, start=1):
                if not plain_row:
                    continue
                if expected_len is None:
                    expected_len = len(plain_row)
                elif len(plain_row) != expected_len:
                    raise CsvFormatError(
                        f"Invalid column count at line {csv_line_no}: expected {expected_len}, got {len(plain_row)}"
                    )
                values = {
                    f"col_{idx}": parse_null(value)
                    for idx, value in enumerate(plain_row)
                }
                record = SourceRecord(
                    line_no=csv_line_no,
                    record_id=f"line:{csv_line_no}",
                    values=values,
                )
                yield record


def build_csv_source(spec: SourceSpec) -> CsvRecordSource:
    """Построить текущий CSV `RowSource` из декларации `SourceSpec`.

    Контракт:
        - поддерживается только `type=file`, `format=csv`;
        - path resolution принадлежит builder'у, а не `DatasetSpec`;
        - параметры времени выполнения должны передаваться через замыкание
          регистрации сборщика в `SourceContainer`.
    """
    if spec.source.type != "file" or spec.source.format != "csv":
        raise ValueError(
            f"{spec.dataset} source spec must be file/csv for current CSV adapter"
        )
    source_path = resolve_source_location(spec)
    csv_options = spec.source.csv_options()
    return CsvRecordSource(
        source_path,
        spec.source.has_header,
        delimiter=csv_options.delimiter,
        encoding=csv_options.encoding,
    )
