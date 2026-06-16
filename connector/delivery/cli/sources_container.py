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

from connector.config.models import AppConfig
from connector.infra.sources.csv.builder import build_csv_source
from connector.infra.sources.factory import SourceAdapterRegistry


def _build_source_registry(*, read_batch_size: int) -> SourceAdapterRegistry:
    """Собрать реестр адаптеров источников с явной регистрацией в composition root."""
    registry = SourceAdapterRegistry()
    registry.register(
        type="file",
        format="csv",
        builder=lambda spec: build_csv_source(spec, read_batch_size=read_batch_size),
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

    app_config = providers.Dependency(instance_of=AppConfig)
    dataset_spec = providers.Dependency(instance_of=object)

    read_batch_size = providers.Callable(
        lambda config: config.extract.read_batch_size, app_config
    )
    registry = providers.Singleton(
        _build_source_registry, read_batch_size=read_batch_size
    )
    source_spec = providers.Factory(lambda s: s.get_source_spec(), s=dataset_spec)
    row_source = providers.Factory(
        lambda registry, spec: registry.create(spec),
        registry=registry,
        spec=source_spec,
    )
