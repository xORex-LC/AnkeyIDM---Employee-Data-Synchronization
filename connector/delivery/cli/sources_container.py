"""DI-субконтейнер выбора runtime источника extract.

Назначение:
    Собирает runtime-граф источника: декларация `SourceSpec` от датасета,
    управляемый DI `SourceAdapterRegistry` и итоговый provider `row_source`.

Граница ответственности:
    Не содержит логики чтения CSV и не интерпретирует downstream-стадии.
    Конкретные адаптеры источников создаются только через registry.
"""

from __future__ import annotations

from dependency_injector import containers, providers

from connector.infra.sources.csv_reader import build_csv_source
from connector.infra.sources.factory import SourceAdapterRegistry


def _build_source_registry() -> SourceAdapterRegistry:
    """Собрать реестр адаптеров источников с явной регистрацией в composition root."""
    registry = SourceAdapterRegistry()
    registry.register(
        type="file",
        format="csv",
        builder=lambda spec: build_csv_source(spec),
    )
    return registry


class SourceContainer(containers.DeclarativeContainer):
    """Субконтейнер runtime источников для `SourceSpec -> RowSource`.

    Назначение:
        Сохраняет выбор адаптера источника внутри delivery composition root.

    Контракт:
        - `dataset_spec` поставляет только декларацию через `get_source_spec()`;
        - `row_source` создаётся через `SourceAdapterRegistry`;
        - внешний accessor `PipelineContainer.row_source` остаётся стабильным.
    """

    dataset_spec = providers.Dependency(instance_of=object)

    registry = providers.Singleton(_build_source_registry)
    source_spec = providers.Factory(lambda s: s.get_source_spec(), s=dataset_spec)
    row_source = providers.Factory(
        lambda registry, spec: registry.create(spec),
        registry=registry,
        spec=source_spec,
    )
