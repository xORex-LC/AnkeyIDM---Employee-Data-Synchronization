# EXTRACT-DEC-002 Implementation Plan

> **Статус**: implementation plan
> **Дата фиксации**: 2026-06-15
> **Основание**: [EXTRACT-DEC-002](../../adr/extract/EXTRACT-DEC-002-polymorphic-source-spec-typed-format-blocks.md)
> **Цель плана**: разбить реализацию DEC-002 на change-set'ы с контролируемым blast radius и сохранить работоспособность CSV runtime после clean-break миграции source spec.

---

## Краткая оценка решения перед реализацией

Обновлённый DEC-002 стал сильнее после перехода от named-block к `format.kind` discriminated union.
Это лучше закрывает реальные риски много-форматного source DSL:

- неизвестный формат должен отбраковываться на spec-load, а не на `SourceAdapterRegistry.create()`;
- `SourceConfig` не разрастается полями `csv`/`db`/`api` и центральным validator'ом;
- CSV-центричный `csv_options()` уходит из общей модели;
- будущие db/api получают место для собственных connection/runtime деклараций без перегруза `location`.

Оставшийся важный технический риск реализации: в Pydantic v2 надо отдельно подтвердить поведение
`Annotated[CsvSourceFormat, Field(discriminator="kind")]` при единственном члене. Если оно не даёт
ожидаемых ошибок дискриминатора для `kind: cvs`, реализация должна всё равно сохранить публичный
контракт DEC-002 через явный before-validator или подготовленный union alias, который будет безболезненно
расширяться вторым членом.

---

## Принципы реализации

- **Clean break без compatibility alias**: старые `format: csv`, `options:`, top-level `has_header`
  должны падать с понятной миграционной ошибкой.
- **Не менять Extractor и RowSource**: DEC-002 меняет DSL/source spec contract, а не extract stream boundary.
- **Не моделировать db/api заранее**: ввести только `CsvSourceFormat`; новые форматы появятся вместе с адаптерами.
- **Сохранять DEC-001 seam**: registry остаётся узким `SourceSpec -> RowSource`, меняется только key extraction
  на `(source.type, source.format.kind)`.
- **Не вводить record-level validation**: `SourceFieldSpec` остаётся advisory.
- **Каждый change-set должен иметь целевые проверки**, даже если project-wide `ruff/mypy` baseline остаётся красным.

---

## Change-Set 0 — Contract Spike and Inventory

### Цель

Проверить техническую реализуемость `SourceFormat` как Pydantic v2 discriminated union с одним текущим
членом и зафиксировать точный blast radius до runtime-правок.

### Объём

- Локально проверить поведение Pydantic для:
  - валидного `format: {kind: csv, ...}`;
  - неизвестного `format: {kind: cvs}`;
  - legacy `format: "csv"`;
  - legacy `options:` и top-level `has_header:`.
- Снять inventory текущих потребителей:
  - `grep -R "source.has_header" connector tests datasets examples docs/dev`
  - `grep -R "csv_options(" connector tests`
  - `grep -R "format: csv\\|options:\\|has_header:" datasets tests examples docs/dev`
- Отделить transform source spec от dictionary source spec:
  - `datasets/dictionaries/**` и dictionary docs не мигрируются в DEC-002.

### Что НЕ входит

- Изменение runtime-кода.
- Миграция YAML.

### Критерий готовности

- Понятно, нужен ли дополнительный validator для one-member union.
- Список файлов для CS1/CS2/CS3 подтверждён grep'ом.

### Проверки

- Минимальный `.venv/bin/python - <<'PY' ... PY` spike или временный unit-test, который не коммитится.
- `git status --short` перед началом изменений.

---

## Change-Set 1 — Source DSL Model Clean Break

### Цель

Заменить нетипизированный `options`/top-level `has_header` на типизированный `SourceFormat` contract
и сделать legacy shape fail-fast на spec-load.

### Объём

- В `connector/domain/transform_dsl/specs/source.py`:
  - переименовать `CsvSourceOptions` в `CsvSourceFormat`;
  - добавить `kind: Literal["csv"]`;
  - перенести `has_header: bool = False` в `CsvSourceFormat`;
  - сохранить validators `delimiter`/`encoding`;
  - ввести `SourceFormat` alias с discriminator `kind`;
  - заменить `SourceConfig.format: str | None` на `format: SourceFormat`;
  - удалить `options`, top-level `has_header`, `csv_options()`;
  - добавить `model_validator(mode="before")` для legacy migration errors:
    - `format` как строка;
    - ключ `options`;
    - top-level `has_header`;
  - оставить after-validator `type=="file" -> location required`;
  - обновить docstring `SourceFieldSpec`: `fields` advisory, не runtime validation.
- Обновить public exports:
  - `connector/domain/transform_dsl/specs/__init__.py`
  - `connector/domain/transform_dsl/__init__.py`
  - заменить `CsvSourceOptions` на `CsvSourceFormat`/`SourceFormat`.
- Обновить unit-тесты модели:
  - валидный csv format;
  - defaults `delimiter`, `encoding`, `has_header`;
  - invalid delimiter/encoding;
  - unknown `kind`;
  - legacy `format: "csv"`;
  - legacy `options`;
  - legacy top-level `has_header`;
  - `type=file` без `location`.

### Что НЕ входит

- Runtime consumers (`build_csv_source`, registry, topology bootstrap).
- Миграция production YAML.

### Важная оговорка

Этот change-set сам по себе может быть не mergeable без CS2/CS3, потому что runtime ещё читает старый
shape. Если нужен строго зелёный commit на каждом шаге, CS1 надо объединить с CS2/CS3 в один commit.
Если нужен review-friendly diff, CS1 можно держать отдельным локальным проходом и не коммитить до CS3.

### Критерий готовности

- `SourceSpec.model_validate(...)` больше не принимает старую форму.
- Новый `SourceSpec.source.format.kind == "csv"` доступен типизированно.
- Старые exports `CsvSourceOptions` удалены из public API.

### Проверки

- `.venv/bin/pytest tests/unit/transform/test_source_spec.py -q`
- `.venv/bin/ruff check connector/domain/transform_dsl/specs/source.py tests/unit/transform/test_source_spec.py`

---

## Change-Set 2 — Runtime Consumers and Registry Key Migration

### Цель

Перевести DEC-001 runtime seam с `(source.type, source.format)` на `(source.type, source.format.kind)`
без изменения `RowSource`/`Extractor`.

### Объём

- В `connector/infra/sources/factory.py`:
  - `create(spec)` извлекает key как `(spec.source.type, spec.source.format.kind)`;
  - `register(type="file", format="csv", ...)` остаётся строковым API composition root;
  - ошибка unsupported adapter перечисляет registered keys, например:
    `Unsupported source adapter: type='file', format='json'. Registered: file/csv`;
  - key normalization остаётся в registry.
- В `connector/infra/sources/csv_reader.py`:
  - `build_csv_source` читает `fmt = spec.source.format`;
  - проверяет `spec.source.type == "file"` и `fmt.kind == "csv"`;
  - передаёт `fmt.has_header`, `fmt.delimiter`, `fmt.encoding` в `PolarsCsvRecordSource`;
  - не вызывает `csv_options()`.
- В `connector/delivery/cli/runtime/topology_bootstrap.py`:
  - заменить `csv_options()` и `source.has_header` на `fmt = source_spec.source.format`;
  - передать `fmt.has_header`, `fmt.delimiter`, `fmt.encoding` в `PolarsSourceAdjacencyReader`.
- В `tests/unit/sources/test_source_registry.py`:
  - обновить helper `_source_spec` на nested `format`;
  - добавить test на registered keys в error message.
- В `tests/unit/delivery/test_sources_container.py`:
  - обновить inline spec/fake ожидания на `format.kind`.

### Что НЕ входит

- Production YAML migration.
- Docs snippets.

### Критерий готовности

- Runtime source builder больше не зависит от `csv_options()` и top-level `has_header`.
- Registry unknown-key ошибка стала операционной и показывает поддерживаемые ключи.

### Проверки

- `.venv/bin/pytest tests/unit/sources/test_source_registry.py tests/unit/delivery/test_sources_container.py tests/unit/infra/test_csv_reader.py -q`
- `.venv/bin/ruff check connector/infra/sources/factory.py connector/infra/sources/csv_reader.py connector/delivery/cli/runtime/topology_bootstrap.py tests/unit/sources/test_source_registry.py tests/unit/delivery/test_sources_container.py`

---

## Change-Set 3 — YAML and Fixture Migration

### Цель

Перевести все transform source specs и тестовые фикстуры на clean-break YAML:
`format: {kind: csv, ...}`.

### Объём

- Мигрировать production source specs:
  - `datasets/employees/source/source.yaml`
  - `datasets/organizations/source/source.yaml`
- Мигрировать examples/templates:
  - `examples/yaml_templates/source.yaml`
- Мигрировать inline YAML/fixtures в tests:
  - `tests/unit/runtime/test_dsl_loader_runtime.py`
  - `tests/unit/domain/dsl/test_registry_path.py`
  - `tests/unit/dataset_dsl/test_yaml_spec.py`
  - все дополнительные matches из grep по transform source shape.
- Не трогать dictionary YAML:
  - `datasets/dictionaries/**`
  - `examples/yaml_templates/dictionary.yaml`
  - dictionary docs/tests.
- Обновить `tests/unit/dataset_dsl/test_yaml_spec.py`:
  - заменить assertions `source.has_header`/`csv_options()` на `source.format.has_header` и прямую модель.

### Что НЕ входит

- Изменение dictionary source DSL.
- Record-level validation по `fields`.

### Критерий готовности

- В transform source specs не осталось legacy shape:
  - `format: csv`
  - top-level `has_header`
  - source-level `options`
- Existing employees/organizations source specs грузятся через новый `SourceConfig`.

### Проверки

- `grep -RIn "format: csv\\|has_header:\\|options:" datasets/employees datasets/organizations examples/yaml_templates/source.yaml tests | head -100`
- `.venv/bin/pytest tests/unit/dataset_dsl/test_yaml_spec.py tests/unit/runtime/test_dsl_loader_runtime.py tests/unit/domain/dsl/test_registry_path.py -q`
- `.venv/bin/pytest tests/unit/transform/test_source_spec.py -q`

---

## Change-Set 4 — Documentation and Public Contract Cleanup

### Цель

Синхронизировать user-facing и developer-facing документацию с новым source spec shape.

### Объём

- Обновить source snippets:
  - `docs/dev/layers/mapper/mapper-dsl.md`
  - `docs/dev/layers/mapper/mapper-core.md`
  - `connector/datasets/README.md`, если там описан source shape.
  - `connector/domain/transform_dsl/README.md`, если там описан source shape.
- В template `examples/yaml_templates/source.yaml` явно подписать:
  - `format.kind` — discriminator;
  - `fields` — advisory, не runtime validation.
- Обновить упоминания `CsvSourceOptions` на `CsvSourceFormat`.
- Обновить README/ADR ссылку на registry key:
  - `(source.type, source.format.kind)`.

### Что НЕ входит

- Любые runtime изменения.

### Критерий готовности

- Docs не предлагают legacy `options`/top-level `has_header`.
- Docs не создают ожидание, что `fields` уже валидирует записи на extract boundary.

### Проверки

- `grep -RIn "SourceConfig.options\\|csv_options\\|format: csv\\|has_header_default" docs connector examples | head -100`
- Ручная сверка DEC-002 и snippets.

---

## Change-Set 5 — End-to-End Hardening and Static Checks

### Цель

Проверить, что DEC-002 не регрессировал CSV execution path и не нарушил архитектурные границы.

### Объём

- Запустить целевые unit/integration/e2e тесты:
  - source spec;
  - source registry;
  - CSV reader;
  - source container;
  - dataset DSL loader;
  - pipeline container e2e.
- Запустить architecture/import-boundary checks.
- Зафиксировать known baseline для project-wide `ruff`/`mypy`, если он остаётся красным вне change-set.

### Критерий готовности

- CSV source pipeline работает на migrated `employees`/`organizations` specs.
- `SourceAdapterRegistry` работает по `(type, format.kind)`.
- Legacy source shape падает до runtime adapter selection.
- `lint-imports` зелёный.

### Проверки

- `.venv/bin/pytest tests/unit/transform/test_source_spec.py tests/unit/sources/test_source_registry.py tests/unit/infra/test_csv_reader.py tests/unit/delivery/test_sources_container.py -q`
- `.venv/bin/pytest tests/unit/dataset_dsl/test_yaml_spec.py tests/unit/runtime/test_dsl_loader_runtime.py tests/unit/domain/dsl/test_registry_path.py -q`
- `.venv/bin/pytest tests/integration/infra/test_polars_csv_reader.py tests/integration/delivery/test_pipeline_container.py tests/e2e/pipelines/test_pipeline_container_e2e.py -q`
- `.venv/bin/pytest tests/architecture -q`
- `.venv/bin/lint-imports`
- `.venv/bin/ruff check <changed files>`
- `.venv/bin/ruff format --check <changed files>`
- `.venv/bin/mypy connector/domain/transform_dsl/specs/source.py connector/infra/sources/factory.py connector/infra/sources/csv_reader.py connector/delivery/cli/runtime/topology_bootstrap.py`

---

## Suggested Commit Split

Если нужен review-friendly ряд коммитов:

1. `EXTRACT-DEC-002: add polymorphic source format model`
   - source model, exports, source-spec unit tests.
2. `EXTRACT-DEC-002: migrate source runtime to format kind`
   - registry key, CSV builder, topology bootstrap, runtime tests.
3. `EXTRACT-DEC-002: migrate source specs to format blocks`
   - datasets, examples, fixtures, dataset loader tests.
4. `EXTRACT-DEC-002: update source spec documentation`
   - docs snippets and README cleanup.

Если нужен always-green history, лучше объединить 1–3 в один commit, потому что source model,
runtime consumers и YAML migration завязаны clean-break контрактом.

---

## Rollback Strategy

- До коммита: `git restore <changed files>` и удалить новые/изменённые фикстуры.
- После коммита: `git revert <commit>`.
- Если regression только в docs/templates: откатывать docs commit отдельно.
- Если regression в runtime: откатывать model/runtime/YAML commits вместе, потому что shape clean-break несовместим со старым runtime.
