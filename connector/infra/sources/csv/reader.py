"""Polars CSV reader — производитель raw-row для CSV

Модуль владеет чтением CSV через Polars, политикой поддерживаемых кодировок,
нормализацией имён колонок и физической семантикой `line_no`. Он отдаёт
raw-row как mapping и не собирает `SourceRecord` самостоятельно.

Ответственность:
    - Читать CSV батчами через `scan_csv().collect_batches()`.
    - Сохранять физические номера строк для header/headerless режима.
    - Классифицировать известные низкоуровневые ошибки через `PolarsCsvErrorClassifier`.

Вне зоны ответственности:
    - Нормализация значений к `str | None`.
    - Формирование `record_id`.
    - Валидация бизнес-полей источника.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Literal

import polars as pl

from connector.domain.ports.transform.source_errors import (
    SourceAdapterError,
    SourceReadError,
)
from connector.infra.sources.csv.errors import PolarsCsvErrorClassifier

_UTF8_ENCODINGS = {"utf8", "utf-8", "utf8-sig", "utf-8-sig"}


class PolarsCsvFrameReader:
    """Читает CSV через Polars и отдаёт raw-row с физическим `line_no`."""

    def __init__(
        self,
        path: str | Path,
        has_header: bool,
        *,
        delimiter: str = ",",
        encoding: str = "utf-8-sig",
        read_batch_size: int = 10_000,
        classifier: PolarsCsvErrorClassifier | None = None,
    ) -> None:
        self.path = str(Path(path))
        self.has_header = has_header
        self.delimiter = delimiter
        self.encoding = encoding
        self.read_batch_size = read_batch_size
        self._classifier = classifier or PolarsCsvErrorClassifier()

    def iter_rows(self) -> Iterator[tuple[int, Mapping[str, object]]]:
        """Итерировать CSV как `(line_no, raw_row)` с сохранением физической семантики строк."""
        row_no = 2 if self.has_header else 1
        try:
            for batch in self._iter_batches():
                batch = self._normalize_columns(batch)
                for row in batch.iter_rows(named=True):
                    yield row_no, row
                    row_no += 1
        except SourceAdapterError:
            raise
        except Exception as exc:
            typed = self._classifier.classify(exc)
            if typed is None:
                raise
            raise typed from exc

    def _iter_batches(self) -> Iterator[pl.DataFrame]:
        """Итерировать Polars-батчи без полной материализации CSV-файла."""
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
        """Нормализовать BOM/headerless имена колонок после чтения Polars."""
        if self.has_header:
            columns = list(batch.columns)
            if columns:
                columns[0] = columns[0].lstrip("\ufeff")
            return batch.rename(dict(zip(batch.columns, columns, strict=True)))
        return batch.rename(
            {column: f"col_{idx}" for idx, column in enumerate(batch.columns)}
        )


def _normalize_encoding(encoding: str) -> Literal["utf8"]:
    """Сузить DSL encoding до поддержанного потокового режима Polars."""
    normalized = encoding.strip().lower().replace("_", "-")
    if normalized not in _UTF8_ENCODINGS:
        raise SourceReadError(
            "Polars CSV streaming currently supports only utf-8/utf-8-sig encodings"
        )
    return "utf8"
