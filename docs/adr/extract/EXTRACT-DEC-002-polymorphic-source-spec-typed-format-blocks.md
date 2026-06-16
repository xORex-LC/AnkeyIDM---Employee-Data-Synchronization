# EXTRACT-DEC-002: Полиморфный spec источника через discriminated union format-моделей

> **Статус**: Принято
> **Дата принятия**: 2026-06-15
> **Решает проблему**: [EXTRACT-PROBLEM-002](./EXTRACT-PROBLEM-002-non-polymorphic-source-spec.md)
> **Участники решения**: @xORex-LC

---

## 📋 Контекст

`SourceConfig` (`domain/transform_dsl/specs/source.py`) моделирует только файловый CSV-случай:
формат-специфичные параметры лежат в нетипизированном `options: dict[str, Any]`, `has_header` — на
верхнем уровне, валидатор форсит csv-семантику. Описать `db`/`api`-источник типобезопасно невозможно
([EXTRACT-PROBLEM-002](./EXTRACT-PROBLEM-002-non-polymorphic-source-spec.md)).

Шов выбора источника готов (реестр `(type, format.kind) → RowSource`,
[EXTRACT-DEC-001](./EXTRACT-DEC-001-source-selection-seam-and-polars-csv-adapter.md)). Решение покрывает
**Фазу 2** (детальный разбор — [EXTRACT_REFACTOR_WORKNOTE](../../notes/extract/EXTRACT_REFACTOR_WORKNOTE.md),
раздел «Детальный дизайн — Фаза 2»; ОВ-B1…B3 закрыты).

> **Эволюция дизайна.** Первоначально (ОВ-B1) был выбран named-block по образцу
> `DictionarySourceSpec`. Ревью рисков показало, что named-block недостаточно OCP для **много-форматных**
> источников (рост `SourceConfig`, центральный validator-hotspot, overloaded `location`,
> CSV-центричный `csv_options()`, поздняя классификация неизвестного формата). Прецедент словарей сюда
> переносится плохо: **словари одно-форматны** (всегда csv), источники — принципиально много-форматны.
> Поэтому ОВ-B1 пересмотрен в пользу **discriminated union** (см. «Почему»).

---

## 🎯 Решение

Сделать формат-специфичную часть `SourceConfig` **discriminated union из per-format моделей** с
дискриминатором `kind` — с единственным членом `csv` сейчас (db/api добавляются вместе со своими
адаптерами, без спекулятивного моделирования).

Состав решения:

1. **Per-format модель `CsvSourceFormat`** (`kind: Literal["csv"]` + `delimiter`/`encoding`/`has_header`),
   самовалидируемая. `SourceConfig.format: SourceFormat` — `Annotated[Union[...], Field(discriminator="kind")]`
   (пока один член `CsvSourceFormat`).
2. **`SourceConfig` остаётся стабильным**: `type`, `location`, `format` (union), `fields`.
   `options: dict` и top-level `has_header` удалены.
3. **Ключ реестра `(type, format.kind)`** — совместим с DEC-001 (раньше `format` был строкой, теперь
   `format.kind`). `type` — coarse-категория, `format.kind` — вариант/драйвер внутри типа (две явные оси).
4. **Неизвестный формат ловится на spec-load**: опечатка `kind: cvs` → ошибка дискриминатора Pydantic
   (а не падение на `registry.create()`).
5. **Операционная ошибка миграции** (`model_validator(mode="before")`): legacy-ключи (`options`,
   top-level `has_header`, `format` как строка) → внятное CLI-сообщение «мигрируйте на `format: {kind: csv, …}`».
6. **`registry.create()` перечисляет поддерживаемые ключи** в сообщении об ошибке (fail-fast capability).
7. **`SourceFieldSpec` явно помечен advisory** (документация контракта, не runtime-валидация) —
   валидация записей по `fields:` вынесена в отдельное решение (ОВ-B2).
8. **Чистый разрыв YAML**: миграция `employees`/`organizations` source.yaml + фикстур.

---

## 🏗️ Архитектурное решение

### Компоненты

**Изменяемые модули**:
- `connector/domain/transform_dsl/specs/source.py` — `CsvSourceOptions` → `CsvSourceFormat` (+`kind`,
  +`has_header`); `SourceFormat` (discriminated union); `SourceConfig` (`format: SourceFormat`, удалены
  `options`/top-level `has_header`/`csv_options()`; before-валидатор миграции; after-валидатор `type==file → location`).
- `connector/infra/sources/factory.py` — ключ `(type, format.kind)`; ошибка `create()` перечисляет registered keys.
- `connector/infra/sources/csv/builder.py` — `build_csv_source`: читает `spec.source.format` (типизированный `CsvSourceFormat`).
- `connector/delivery/cli/runtime/topology_bootstrap.py` — второй CSV-потребитель: `spec.source.format.{delimiter,encoding,has_header}`.
- `datasets/employees/source/source.yaml`, `datasets/organizations/source/source.yaml` — миграция на `format: {kind: csv, …}`.
- `transform_dsl/specs/__init__.py`, `transform_dsl/__init__.py` — экспорт `CsvSourceFormat`/`SourceFormat` (вместо `CsvSourceOptions`).
- Тесты/фикстуры source-spec.

**Не меняются**: `SourceAdapterRegistry` (контракт `create(spec) → RowSource`), `resolve_source_location`
(file-path), `Extractor`, `RowSource`, `SourceRecord`/`TransformResult`, словари (`DictionarySourceSpec`).

### Интерфейсы

```python
# transform_dsl/specs/source.py
class CsvSourceFormat(DslBaseModel):
    kind: Literal["csv"]
    delimiter: str = ","
    encoding: str = "utf-8-sig"
    has_header: bool = False
    # field-validators delimiter/encoding — без изменений (перенесены сюда)

# один член сейчас; новый формат = новая модель + расширение Union (OCP)
SourceFormat = Annotated[CsvSourceFormat, Field(discriminator="kind")]

class SourceConfig(DslBaseModel):
    type: Literal["file", "db", "api"]
    location: str | None = None
    format: SourceFormat
    fields: list[SourceFieldSpec] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_shape(cls, data): ...   # options / top-level has_header / format:str → миграционная ошибка

    @model_validator(mode="after")
    def _validate_type(self) -> "SourceConfig": ...   # type=="file" → location required
```

### YAML (миграция)

```yaml
# Было
source:
  type: file
  format: csv
  location: "source_employees.csv"
  has_header: true
  options: { delimiter: ";", encoding: "utf-8-sig" }
  fields: [...]

# Стало
source:
  type: file
  location: "source_employees.csv"
  format: { kind: csv, delimiter: ";", encoding: "utf-8-sig", has_header: true }
  fields: [...]   # advisory: документация контракта, не runtime-валидация (ОВ-B2)
```

### Поток данных

```
DatasetSpec.get_source_spec() → SourceSpec (format: дискриминированный CsvSourceFormat)
        ↓
SourceAdapterRegistry.create(spec)  [ключ (type, format.kind)] → RowSource
        ↓
build_csv_source(spec): fmt = spec.source.format → PolarsCsvRecordSource(delimiter=fmt.delimiter, …)
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ OCP по-настоящему: новый формат = **новая модель-член + расширение Union**; существующие
  format-модели и `SourceConfig` не редактируются, нет центрального validator-hotspot.
- ✅ Неизвестный/опечатанный формат отвергается **на spec-load** (ошибка дискриминатора), а не на
  `registry.create()` — ранний и понятный сигнал.
- ✅ Каждый формат владеет своими полями/семантикой/валидацией → `type` и `format.kind` — две явные
  оси; `location`/connection локализуются в per-format моделях по мере появления (db dsn/api endpoint).
- ✅ Нет CSV-центричных accessor'ов (`csv_options()`); потребитель читает типизированный `spec.source.format`.
- ✅ Без спекулятивного дизайна: член один (csv); db/api модели добавляются с их адаптерами.

**Недостатки (компромиссы)**:
- ⚠️ Чуть больше «церемонии» для одного члена сейчас (Union из одного типа) — оправдано тем, что
  структура spec — breaking-migration surface; решаем один раз.
- ⚠️ **Сознательное расхождение с прецедентом словарей** (named-block): словари одно-форматны, источники
  много-форматны — разные реалии масштабирования; зафиксировано как осознанный выбор.
- ⚠️ Breaking YAML → миграция prod-спек и фикстур (но `extra="forbid"` + before-валидатор делают это
  fail-fast с операционным сообщением).

**Альтернативы, которые отклонили**:
- ❌ **Named-block (`csv:`/`db:`/… поля на `SourceConfig`)** — первоначальный ОВ-B1: рост `SourceConfig`
  и центрального validator при росте форматов (risk 3), overloaded `location` (risk 5), давление на
  `db_options()`/`api_options()` (risk 7), неизвестный формат — только на registry (risk 1/2). Для
  одно-форматных словарей приемлемо, для много-форматных источников — нет.
- ❌ **Полные `DbSourceOptions`/`ApiSourceOptions` сейчас**: спекулятивно (нет адаптеров-потребителей);
  поля почти наверняка неверны; half-bridge (spec ок, `create()` падает).
- ❌ **`options: dict` + ad-hoc валидация в адаптере**: теряется декларативная валидация на границе DSL,
  дублирование по адаптерам.
- ❌ **Валидация записей по `fields:` в DEC-002** (ОВ-B2): record-level concern, отдельное решение.
- ❌ **Мягкая миграция/back-compat алиас**: против clean-break стиля (CONFIG-DEC, DEC-001).

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/domain/transform_dsl/specs/source.py` | `CsvSourceFormat` (+`kind`/`has_header`), `SourceFormat` union, `SourceConfig` (`format: SourceFormat`, before/after-валидаторы, удалены `options`/`has_header`/`csv_options`) |
| `connector/infra/sources/factory.py` | ключ `(type, format.kind)`; `create()` перечисляет registered keys |
| `connector/infra/sources/csv/builder.py` | `build_csv_source` читает `spec.source.format` (`CsvSourceFormat`) |
| `connector/delivery/cli/runtime/topology_bootstrap.py` | `spec.source.format.{delimiter,encoding,has_header}` |
| `datasets/employees/source/source.yaml`, `datasets/organizations/source/source.yaml` | миграция на `format: {kind: csv, …}` |
| `transform_dsl/specs/__init__.py`, `transform_dsl/__init__.py` | экспорт `CsvSourceFormat`/`SourceFormat` |
| `tests/unit/transform/test_source_spec.py`, `tests/unit/dataset_dsl/test_yaml_spec.py`, прочие фикстуры | миграция + кейсы union/дискриминатора/миграционной ошибки |

### Инварианты

1. **OCP**: добавление формата не редактирует существующие format-модели и не наращивает центральный validator.
2. **Спец-тайм классификация**: неизвестный `format.kind` → ошибка дискриминатора на spec-load.
3. **Совместимость шва**: ключ реестра `(type, format.kind)`, контракт `RowSource` неизменны.
4. **Изоляция**: словари и доменное ядро extract не затронуты.
5. **Fail-fast миграции**: legacy-shape (`options`/top-level `has_header`/`format:str`) → операционная ошибка.
6. **`fields:` — advisory**: не enforced в DEC-002; помечено в модели и YAML-шаблоне.

---

## 🧪 Валидация решения

**Тесты (план)**:
- ✅ `unit`: валидный `format: {kind: csv, …}` → типизированный `CsvSourceFormat`; дефолты при опущенных полях.
- ✅ `unit`: `format: {kind: cvs}` (опечатка) → ошибка дискриминатора (spec-load), не доходит до registry.
- ✅ `unit`: legacy `options:` / top-level `has_header:` / `format: "csv"` → операционная миграционная ошибка.
- ✅ `unit`: `type=="file"` без `location` → ошибка.
- ✅ `unit`: `SourceAdapterRegistry.create()` на незарегистрированный ключ → ошибка с перечнем registered keys.
- ✅ `integration`/parity: `build_csv_source` и `topology_bootstrap` читают `spec.source.format` и работают идентично.
- ✅ Полный прогон employees/organizations не деградирует.

**Проверка статикой**: `ruff`, `mypy connector/` (discriminated union типизируется), `lint-imports` (границы не меняются), `pytest`.

---

## ⚠️ Риски и ограничения (ревью — все 8 учтены)

| # | Риск | Диспозиция |
|---|---|---|
| 1 | `type: db/api` без модели формата проходит DSL, падает на `create()` | Union: формат без модели-члена не пройдёт дискриминатор **на spec-load**. `create()` дополнительно fail-fast с перечнем ключей |
| 2 | Опечатка `format: cvs` доходит до registry | Дискриминатор `kind` отвергает на spec-load (не доходит до registry) |
| 3 | Named-block раздувает `SourceConfig` + центральный validator | Снято union'ом: per-format модели самовалидируются; `SourceConfig` стабилен |
| 4 | `type`/`format` — разные оси, один ключ | Явно: `type`=категория, `format.kind`=вариант/драйвер; ключ `(type, format.kind)` задокументирован |
| 5 | `location` overloaded (path/DSN/endpoint) | Union локализует connection в per-format моделях (db/api — при их адаптерах); сейчас `location`=file-path |
| 6 | `SourceFieldSpec` выглядит контрактно, но не исполняется | Явно помечен advisory (docstring + YAML-коммент); форвард на ОВ-B2 |
| 7 | `csv_options()` CSV-центричен; давление на `db_options()`… | Метод удалён; потребитель читает типизированный `spec.source.format` |
| 8 | Pydantic-ошибки `extra="forbid"` неоперационны | `model_validator(mode="before")` даёт внятное миграционное сообщение для legacy-ключей |

**Scope-out (явно)**:
- db/api format-модели + per-format connection-резолв (DSN/endpoint, секреты из vault, курсорный streaming,
  строковый контракт `values`, контентный `record_id`) — вместе с их адаптерами (P-003/будущий DEC);
  spec структурно готов (см. worknote «what-it-takes-to-add-a-format»).
- Валидация записей по `fields:` — отдельное record-level решение (ОВ-B2; кандидат к P-003 `RecordBuilder`).

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `SourceConfig`/format-модели | API | `options`/`has_header`/`csv_options()` → `format: SourceFormat` (union) |
| `factory.create` | Минимальное | ключ `(type, format.kind)` + перечень ключей в ошибке |
| `build_csv_source`, `topology_bootstrap` | Минимальное | читают `spec.source.format` |
| source.yaml (employees, organizations) | Миграция | `format: {kind: csv, …}` |
| `resolve_source_location` / `Extractor` / `RowSource` | Нет | контракт неизменен |
| Словари (`DictionarySourceSpec`) | Нет | отдельная модель |
| Тесты/фикстуры | Обновление | миграция + кейсы union/дискриминатора/миграции |

---

## 📚 Документация

**Обновлено в рамках реализации**:
- ✅ `examples/yaml_templates/source.yaml` — `format: {kind: csv, …}` + комментарии про discriminator и advisory `fields`.
- ✅ `connector/datasets/README.md`, `connector/domain/transform_dsl/README.md`, `connector/infra/sources/README.md`,
  `docs/dev/layers/mapper/*` — source-spec snippet'ы и registry key синхронизированы с `(source.type, source.format.kind)`.

---

## 🔗 Связанные документы

- [EXTRACT-PROBLEM-002](./EXTRACT-PROBLEM-002-non-polymorphic-source-spec.md) — решаемая проблема
- [EXTRACT-DEC-001](./EXTRACT-DEC-001-source-selection-seam-and-polars-csv-adapter.md) — шов выбора источника (ключ `(type, format)`)
- [EXTRACT-PROBLEM-003](./EXTRACT-PROBLEM-003-monolithic-source-adapter-no-isolation.md) — декомпозиция адаптера (P-003; `fields`-валидация/`record_id`)
- [EXTRACT_REFACTOR_WORKNOTE](../../notes/extract/EXTRACT_REFACTOR_WORKNOTE.md) — детальный дизайн Фазы 2, разбор 8 рисков, «what-it-takes-to-add-a-format»
- `connector/domain/dictionary_dsl/specs.py` — named-block прецедент (одно-форматный; почему не переносим)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-06-15 | Дизайн зафиксирован в worknote (Фаза 2); ОВ-B1…B3 закрыты (named-block) |
| 2026-06-15 | Ревью 8 рисков → ОВ-B1 пересмотрен: discriminated union per-format; решение принято |
