# connector/datasets

## Назначение

Слой датасет-плагина. Изолирует специфику конкретного датасета от универсальных use case'ов и стадий пайплайна.

Каждый датасет реализует `DatasetSpec` — единый контракт, через который usecases и delivery получают DSL-спеки стадий, adapters и каталог ошибок.

## Структура

| Файл | Назначение |
|---|---|
| `spec.py` | `DatasetSpec` (Protocol) — контракт плагина: `build_spec_for(stage_type)`, `get_source_spec()`, `get_apply_adapter()`, `get_diagnostic_catalog()`, `get_report_adapter()` |
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

## Extract source seam

В рамках `EXTRACT-DEC-001` слой датасета не строит runtime source adapter.

- `get_source_spec()` — accessor декларации источника (`SourceSpec`) без создания adapter.
- Выбор конкретного `RowSource` выполняется в `delivery` composition root через `SourceAdapterRegistry`.
- Ключ выбора adapter после `EXTRACT-DEC-002` — `(source.type, source.format.kind)`.
- CSV-параметры описываются в typed format-блоке `source.format`, а `fields` остаётся advisory-описанием,
  не runtime-валидацией строк на extract-boundary.
- `datasets` не импортирует `infra.sources.*`; runtime path resolution принадлежит source builder'ам.
