"""Accessor времени выполнения для уже загруженного YAML-управляемого `DatasetSpec`.

Назначение:
    Предоставляет доступ к заранее загруженному YAML-снимку датасета без повторного
    чтения YAML-файлов.

Граница ответственности:
    - Владеет доступом к заранее загруженному снимку датасета и сборкой apply/report адаптеров.
    - Не читает YAML-файлы повторно.
    - Не выбирает фабрику датасета и не создаёт runtime-адаптер источника.
"""

from __future__ import annotations

from connector.datasets.apply_adapter import OperationApplyAdapter
from connector.datasets.spec import ReportAdapter, UnsupportedStageError
from connector.datasets.yaml_spec_loader import LoadedYamlDatasetArtifacts
from connector.domain.dataset_dsl.catalog_compiler import compile_diagnostic_catalog
from connector.domain.dataset_dsl.params_compiler import resolve_params_builder
from connector.domain.dataset_dsl.payload_compiler import SinkDrivenPayloadBuilder
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.ports.secrets.provider import SecretProviderProtocol
from connector.domain.ports.target.apply import ApplyAdapterProtocol
from connector.domain.transform_dsl.specs import SourceSpec


class YamlDatasetSpec:
    """Реализация `DatasetSpec` поверх YAML-снимка.

    Назначение:
        Предоставляет изолированные копии DSL-спецификаций и собирает
        apply/report адаптеры уровня датасета.

    Контракт:
        - `build_spec_for()` не делает I/O и возвращает изолированную копию спецификации;
        - `get_source_spec()` возвращает изолированную копию декларации источника;
        - `get_apply_adapter()` использует только заранее загруженный `SinkSpec` и dataset DSL.
    """

    def __init__(
        self,
        artifacts: LoadedYamlDatasetArtifacts,
        secrets: SecretProviderProtocol | None = None,
    ) -> None:
        self.dataset_name = artifacts.dataset_name
        self._artifacts = artifacts
        self._secrets = secrets

    def build_spec_for(self, stage_type: str) -> object:
        """Назначение:
            Вернуть заранее загруженную спецификацию стадии по ключу без повторной загрузки YAML.

        Контракт:
            - неизвестная стадия → `UnsupportedStageError`;
            - каждая выдача изолирована через `model_copy(deep=True)`.
        """
        stage_spec = self._artifacts.stage_specs.get(stage_type)
        if stage_spec is None:
            raise UnsupportedStageError(stage_type, dataset=self.dataset_name)
        return stage_spec.model_copy(deep=True)

    def get_source_spec(self) -> SourceSpec:
        """Назначение:
            Вернуть заранее загруженную source-спецификацию без создания runtime-адаптера источника.

        Контракт:
            - не читает source YAML повторно;
            - каждая выдача изолирована через `model_copy(deep=True)`;
            - выбор runtime-адаптера остаётся вне datasets-слоя.
        """
        return self._artifacts.source_spec.model_copy(deep=True)

    def get_report_adapter(self) -> ReportAdapter:
        r = self._artifacts.dataset_dsl.report
        return ReportAdapter(
            identity_label=r.identity_label,
            conflict_code=r.conflict_code,
            conflict_field=r.conflict_field,
        )

    def get_apply_adapter(self) -> ApplyAdapterProtocol:
        """Назначение:
            Собрать apply-адаптер поверх заранее загруженной sink-спецификации и dataset DSL.

        Контракт:
            - не читает sink YAML повторно;
            - каждый вызов создаёт новый экземпляр адаптера.
        """
        sink_spec = self._artifacts.sink_spec
        apply = self._artifacts.dataset_dsl.apply
        payload_builder = SinkDrivenPayloadBuilder(
            sink_spec=sink_spec,
            defaults=dict(apply.payload.defaults),
            conditional_fields=list(apply.payload.conditional_fields),
        )
        params_builder = resolve_params_builder(apply.params)
        return OperationApplyAdapter(
            operation_alias=apply.operation_alias,
            payload_builder=payload_builder,
            dataset=self.dataset_name,
            params_builder=params_builder,
            secrets=self._secrets,
        )

    def get_diagnostic_catalog(self, strict: bool) -> ErrorCatalog:
        return compile_diagnostic_catalog(
            self._artifacts.dataset_dsl.diagnostics,
            strict=strict,
        )
