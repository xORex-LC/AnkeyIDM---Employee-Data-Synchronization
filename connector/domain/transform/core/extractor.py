"""Extractor — доменная граница входа потока источника в transform pipeline

Модуль оборачивает `SourceRecord`, полученные от `RowSource`, в универсальный
`TransformResult`. Он также переводит потоковые отказы источника в
диагностики extract-стадии, не зная конкретного типа источника.

Ответственность:
    - Сохранять ленивую итерацию исходных `SourceRecord`.
    - Создавать `TransformResult[None]` для успешных записей extract.
    - Классифицировать доменные исключения источника в diagnostic codes.

Вне зоны ответственности:
    - Чтение файлов, SQL, HTTP или других внешних источников.
    - Разбор форматов и маппинг исключений infra-библиотек.
    - Бизнес-валидация полей источника.
"""

from __future__ import annotations

from typing import Iterable

from connector.domain.models import DiagnosticStage, RowRef
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.context import error as diag_error
from connector.domain.ports.transform.source_errors import (
    SourceParseError,
    SourceReadError,
)
from connector.domain.ports.transform.sources import RowSource
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.source_record import SourceRecord


class Extractor:
    """
    Назначение/ответственность:
        Унифицированное ядро извлечения: оборачивает SourceRecord в TransformResult
        и фиксирует фатальные ошибки источника как EXTRACT-диагностику.
    """

    def __init__(self, source: RowSource, catalog: ErrorCatalog) -> None:
        self.source = source
        self.catalog = catalog

    def run(self) -> Iterable[TransformResult[None]]:
        """
        Назначение:
            Считать источник и обернуть записи в TransformResult.

        Алгоритм:
            - Каждую запись источника возвращает как TransformResult без row.
            - Типизированные ошибки источника фиксирует как granular EXTRACT-диагностики.
            - Неизвестные ошибки источника фиксирует как резервную EXTRACT-ошибку.
        """
        try:
            for record in self.source:
                yield TransformResult(
                    record=record,
                    row=None,
                    row_ref=None,
                    match_key=None,
                    errors=(),
                    warnings=(),
                )
        except SourceReadError as exc:
            yield self._source_failure_result(exc, code="SOURCE_READ_FAILED")
        except SourceParseError as exc:
            yield self._source_failure_result(exc, code="SOURCE_PARSE_FAILED")
        except Exception as exc:  # noqa: BLE001
            yield self._source_failure_result(exc, code="SOURCE_ERROR")

    def _source_failure_result(
        self, exc: Exception, *, code: str
    ) -> TransformResult[None]:
        """
        Назначение:
            Создать единый synthetic-result для потокового отказа источника.

        Контракт:
            Отказ на уровне источника не относится к конкретной входной строке, поэтому
            использует стабильную ссылку `source` и synthetic SourceRecord.
        """
        row_ref = RowRef(
            line_no=None,
            row_id="source",
            identity_primary=None,
            identity_value=None,
        )
        error = diag_error(
            catalog=self.catalog,
            stage=DiagnosticStage.EXTRACT,
            code=code,
            field=None,
            message=str(exc),
            record_ref=row_ref,
        )
        return TransformResult(
            record=SourceRecord(line_no=0, record_id="source", values={}),
            row=None,
            row_ref=row_ref,
            match_key=None,
            errors=(error,),
            warnings=(),
        )
