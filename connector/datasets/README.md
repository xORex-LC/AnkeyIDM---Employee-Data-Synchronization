# connector/datasets

## Назначение

Слой датасет-плагина. Изолирует специфику конкретного датасета от универсальных use case'ов и стадий пайплайна.

Каждый датасет реализует `DatasetSpec` — единый контракт, через который usecases и delivery получают DSL-спеки стадий, adapters и каталог ошибок.

## Структура

| Файл | Назначение |
|---|---|
| `spec.py` | `DatasetSpec` (Protocol) — контракт плагина: `build_spec_for(stage_type)`, `get_source_spec()`, legacy `build_record_source()`, `get_apply_adapter()`, `get_diagnostic_catalog()`, `get_report_adapter()` |
| `registry.py` | `DatasetRegistry` — auto-discovery датасетов из `datasets/registry.yaml`; выбор factory по имени |
| `yaml_spec.py` | `YamlDatasetSpec` — реализация `DatasetSpec` поверх YAML-артефактов |
| `yaml_spec_loader.py` | Загружает все YAML-файлы датасета в `DatasetArtifacts` |
| `apply_adapter.py` | `OperationApplyAdapter` — универсальный `ApplyAdapterProtocol`: гидрирует секреты, строит payload через `payload_builder`, отдаёт `RequestSpec` |
| `cache_sync.py` | `CacheSyncAdapterProtocol` — стратегия синхронизации кэша: `get_item_key()`, `is_deleted()`, `map_target_to_cache()` |

## Зависимости

**Зависит от:** `domain/ports/`, `domain/dsl/loader/`, `domain/transform_dsl/`, `domain/planning/plan_models.py`.  
**Используется:** `delivery/cli/containers.py`, usecases (через `DatasetSpec`), `infra/cache/sync/`.

## Правило

Датасет-плагин знает о своих DSL-файлах, но не содержит бизнес-логики трансформации. Новый датасет = новый YAML в `datasets/<name>/` + запись в `datasets/registry.yaml`. Python-код менять не требуется.

## Extract source transition

В рамках `EXTRACT-DEC-001` слой датасета постепенно перестаёт строить runtime source adapter.
Переходное состояние:

- `get_source_spec()` — новый accessor декларации источника (`SourceSpec`) без создания adapter.
- `build_record_source()` — legacy runtime accessor, пока `row_source` ещё не перенесён в source registry / composition root.

После завершения source-selection change-set `build_record_source()` будет удалён из `DatasetSpec`, а выбор конкретного `RowSource` перейдёт в `delivery` composition root.
