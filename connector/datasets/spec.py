"""
Назначение:
    Контракты dataset-плагина для transform/planning/apply сценариев.

    DatasetSpec (Protocol) — narrowed: DSL configuration + adapters.
    Phase 2 (DEC-009): typed build_*_spec() заменены на generic build_spec_for(stage_type).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.ports.target.apply import ApplyAdapterProtocol
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform_dsl.specs import SourceSpec


@dataclass(frozen=True)
class ReportAdapter:
    """
    Назначение:
        Набор констант/лейблов для отчётов по датасету.
    """
    identity_label: str
    conflict_code: str
    conflict_field: str


class UnsupportedStageError(Exception):
    """
    Назначение:
        Стадия не поддерживается данным датасетом.
    """

    def __init__(self, stage_type: str, *, dataset: str) -> None:
        self.stage_type = stage_type
        self.dataset = dataset
        super().__init__(
            f"Dataset '{dataset}' does not support stage type '{stage_type}'"
        )


class DatasetSpec(Protocol):
    """
    Назначение:
        Контракт плагина датасета: DSL configuration + adapters.

    Граница:
        - build_spec_for(stage_type) — generic accessor для DSL-спецификации стадии (Phase 2, DEC-009).
        - get_source_spec() — доступ к декларации источника без создания runtime adapter.
        - build_record_source() — legacy runtime-доступ к источнику данных до завершения EXTRACT-DEC-001.
        - get_report_adapter() / get_apply_adapter() — отчётные/apply адаптеры.
        - get_diagnostic_catalog() — каталог ошибок.
    """

    dataset_name: str

    def build_spec_for(self, stage_type: str) -> object: ...
    def get_source_spec(self) -> SourceSpec: ...
    def build_record_source(self) -> Iterable[SourceRecord]: ...
    def get_report_adapter(self) -> ReportAdapter: ...
    def get_apply_adapter(self) -> ApplyAdapterProtocol: ...
    def get_diagnostic_catalog(self, strict: bool) -> ErrorCatalog: ...
