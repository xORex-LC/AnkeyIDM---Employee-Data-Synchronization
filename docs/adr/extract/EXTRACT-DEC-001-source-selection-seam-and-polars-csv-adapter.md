# EXTRACT-DEC-001: Шов выбора источника (registry + composition root) и миграция CSV на polars

> **Статус**: Принято
> **Дата принятия**: 2026-06-15
> **Решает проблему**: [EXTRACT-PROBLEM-001](./EXTRACT-PROBLEM-001-source-selection-hardcoded-and-cross-layer-coupling.md)
> **Участники решения**: @xORex-LC

---

## 📋 Контекст

Выбор и инстанциация источника происходят в `YamlDatasetSpec.build_record_source()`
(`connector/datasets/yaml_spec.py`): метод хардкодит `file/csv`, напрямую импортирует
`CsvRecordSource` из `infra` (известный долг — `ignore_imports` в `pyproject.toml`) и не имеет точки
расширения для новых источников ([EXTRACT-PROBLEM-001](./EXTRACT-PROBLEM-001-source-selection-hardcoded-and-cross-layer-coupling.md)).
При этом доменное ядро (`Extractor` + порт `RowSource` + контракт `SourceRecord`/`TransformResult`)
уже источник-агностично — проблема только в точке выбора и в cross-layer связности.

Решение покрывает **Фазы 0–1** дорожной карты рефактора (детальный разбор и альтернативы —
[EXTRACT_REFACTOR_WORKNOTE](../../notes/extract/EXTRACT_REFACTOR_WORKNOTE.md)). Внутренняя
SRP-декомпозиция адаптера ([EXTRACT-PROBLEM-003](./EXTRACT-PROBLEM-003-monolithic-source-adapter-no-isolation.md))
и полиморфный spec источника ([EXTRACT-PROBLEM-002](./EXTRACT-PROBLEM-002-non-polymorphic-source-spec.md))
сознательно вне объёма; шов проектируется так, чтобы они легли поверх без переделок.

---

## 🎯 Решение

Вынести выбор источника из `datasets`-слоя в **реестр-фабрику в `infra`**, вызываемую из composition
root, а `datasets` оставить только поставщиком декларации `SourceSpec`. Одновременно перевести
физическое чтение CSV со stdlib-`csv` на **polars** (ранее зафиксированное направление «extract
работает с данными через polars»), сохранив bounded-memory streaming.

Состав решения:

1. **`SourceAdapterRegistry`** (`infra/sources/factory.py`) — реестр builder'ов по ключу
   `(source.type, source.format)`; `create(spec) → RowSource`.
2. **`DatasetSpec`** отдаёт `get_source_spec() → SourceSpec` вместо `build_record_source()`; из
   `datasets/yaml_spec.py` убирается импорт infra.
3. **DI-субконтейнер `delivery/cli/sources_container.py`** (по образцу `dictionaries_container`):
   владеет реестром, явно регистрирует CSV-builder, предоставляет провайдер `row_source`.
4. **polars-адаптер** `PolarsCsvRecordSource` (`infra/sources/csv_reader.py`) на
   `pl.scan_csv().collect_batches()` + builder `build_csv_source(spec)` co-located в модуле адаптера.
5. **`ExtractConfig.read_batch_size`** в `AppConfig` (операционный knob, не DSL).
6. **Снятие `ignore_imports`** в `pyproject.toml` + architecture-тест границы `datasets → infra`.
7. **Фаза 0 (housekeeping)**: фикс stale-доков (`infra/sources/README.md`) — описание
   CSV-источника как реализующего `SourceMapper` на polars неверно: source-адаптер реализует
   `RowSource`. **`SourceMapper` НЕ трогаем** — это живой порт map-стадии (см. scope-out ниже).

---

## 🏗️ Архитектурное решение

### Компоненты

**Новые модули**:
- `connector/infra/sources/factory.py` — `SourceAdapterRegistry` (+ тип `SourceBuilder`).
- `connector/delivery/cli/sources_container.py` — DI-субконтейнер источника.
- `connector/config/models.py` → `ExtractConfig` (новая секция AppConfig).

**Изменяемые компоненты**:
- `connector/infra/sources/csv_reader.py` — `CsvRecordSource` → `PolarsCsvRecordSource` (polars,
  batched) + `build_csv_source(spec)`.
- `connector/datasets/spec.py` — Protocol `DatasetSpec`: `build_record_source()` → `get_source_spec()`.
- `connector/datasets/yaml_spec.py` — реализация `get_source_spec()`; удалён `import CsvRecordSource`.
- `connector/delivery/cli/containers.py` — подключение `sources_container`; провайдер `row_source`
  переезжает в субконтейнер.
- `pyproject.toml` — удалён `ignore_imports` `datasets.yaml_spec -> infra.sources.csv_reader`.
- `examples/configs/config_example.yml` — секция `extract`.
- Фаза 0 (только доки): `connector/infra/sources/README.md`.
  `connector/domain/ports/transform/sources.py` **не меняется** (`SourceMapper` — живой порт map-стадии).

### Интерфейсы

```python
# infra/sources/factory.py
SourceBuilder = Callable[[SourceSpec], RowSource]

class SourceAdapterRegistry:
    def register(self, *, type: str, format: str | None, builder: SourceBuilder) -> None: ...
    def create(self, spec: SourceSpec) -> RowSource: ...   # нет ключа → стабильная ошибка

# infra/sources/csv_reader.py
def build_csv_source(spec: SourceSpec) -> RowSource: ...    # co-located builder
class PolarsCsvRecordSource:                                # реализует RowSource
    def __iter__(self) -> Iterable[SourceRecord]: ...

# datasets/spec.py (Protocol DatasetSpec)
def get_source_spec(self) -> SourceSpec: ...               # вместо build_record_source()

# config/models.py
class ExtractConfig(BaseModel):
    read_batch_size: int = Field(default=10_000, gt=0)
```

### Поток данных

```
DatasetSpec.get_source_spec() → SourceSpec
        ↓ (sources_container, composition root)
SourceAdapterRegistry.create(spec)  [ключ (type, format)] → RowSource
        ↓
PolarsCsvRecordSource (pl.scan_csv().collect_batches() → batch.iter_rows → SourceRecord)
        ↓
Extractor(row_source, catalog)  → TransformResult[None]   (domain, без изменений)
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ OCP: новый источник = новый builder + одна строка регистрации; `create()`, `datasets`, `domain`
  не меняются.
- ✅ Чистый import-boundary: `datasets`/`domain`/`usecases` больше не зависят от `infra`;
  `ignore_imports` снимается структурно, а не маскируется.
- ✅ Консистентность: повторяет паттерн подсистемы справочников (polars-чтение в infra, разделение
  чтения и обёртки, выделенный DI-субконтейнер) и registry-паттерн (`OperationRegistry`).
- ✅ Единый data-стек: polars даёт нативные encoding/null/типы и убирает самописный `csv`/`parse_null`.
- ✅ Тест-изоляция: реестр — DI-managed instance (чистый `override`/reset), без глобального состояния.

**Недостатки (компромиссы)**:
- ⚠️ Добавление адаптера трогает `sources_container` одной строкой `register(...)` (приемлемо: это
  explicit-wiring в composition root — цена за тестируемость и трассируемость).
- ⚠️ Меняется Protocol-контракт `DatasetSpec` (`build_record_source` → `get_source_spec`) — но
  единственный потребитель `row_source`-провайдер (малый блейст-радиус).
- ⚠️ polars `read_csv` eager; для streaming используем `scan_csv().collect_batches()` (чуть сложнее прямого чтения,
  но сохраняет bounded-memory контракт).

**Альтернативы, которые отклонили**:
- ❌ **Module-level self-register адаптеров**: глобальное mutable-состояние, регистрация как импортный
  side-effect, ухудшение тест-изоляции, уход wiring из composition root — против DI-архитектуры
  проекта и прецедента `dictionaries_container` (разбор ОВ-1.2 в worknote).
- ❌ **`read_batch_size` в source DSL (`source.yaml`)**: batch size не меняет значения записей —
  это операционный knob, а не контракт данных; место в AppConfig (прецедент
  `resolver.resolve_batch_size`, `matching_runtime.match_batch_size`) (разбор ОВ-1.3).
- ❌ **`scan_csv().collect(streaming=True)` для построчной выдачи**: материализует полный DataFrame
  перед итерацией строк — теряется bounded-memory; `scan_csv().collect_batches()` корректнее для row-stream.
- ❌ **Оставить выбор в `datasets` за локальной абстракцией**: не снимает cross-layer импорт infra и
  `ignore_imports` (Вариант 2 в PROBLEM-001).
- ❌ **Гранулярные коды ошибок (`SOURCE_READ_FAILED`/`SOURCE_PARSE_FAILED`) уже сейчас**: их владелец —
  `ErrorClassifier`-сотрудник из P-003; ввод раньше классификатора разносит одно решение по фазам
  (разбор ОВ-1.4).
- ❌ **Явный `driver`-идентификатор в spec вместо `(type, format)`**: расширяет схему раньше нужды;
  кандидат в P-002, если появится >1 реализации на один `(type, format)`.

---

## 🛠️ Реализация

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/infra/sources/factory.py` | Создан `SourceAdapterRegistry` + `SourceBuilder` |
| `connector/infra/sources/csv_reader.py` | `CsvRecordSource` → `PolarsCsvRecordSource` (polars batched) + `build_csv_source()` |
| `connector/delivery/cli/sources_container.py` | Создан DI-субконтейнер: реестр, регистрация CSV-builder, `row_source` |
| `connector/datasets/spec.py` | Protocol: `build_record_source()` → `get_source_spec()` |
| `connector/datasets/yaml_spec.py` | Реализация `get_source_spec()`; удалён импорт infra |
| `connector/delivery/cli/containers.py` | Подключение `sources_container`; перенос `row_source` |
| `connector/config/models.py` | `ExtractConfig.read_batch_size`; включён в `AppConfig` |
| `examples/configs/config_example.yml` | Секция `extract:` |
| `pyproject.toml` | Удалён `ignore_imports` для `datasets.yaml_spec -> infra.sources.csv_reader` |
| `connector/infra/sources/README.md` | Фаза 0: актуализация (polars; source-адаптер реализует `RowSource`, а не `SourceMapper`) |
| `tests/unit/sources/`, `tests/integration/sources/`, `tests/architecture/` | Новые тесты (см. Валидация) |

### Инварианты

1. **Источник-агностичность**: `Extractor` и `datasets` не знают о конкретном адаптере; знание о
   формате локализовано в `infra/sources/` + регистрации в `sources_container`.
2. **Import-boundary**: `connector.datasets.*` не импортирует `connector.infra.*` (без `ignore_imports`).
3. **Streaming**: пик памяти адаптера ограничен `read_batch_size`, а не размером файла.
4. **Паритет идентичности/строк**: `record_id = "line:{n}"`, нумерация строк сохраняет текущую
   семантику (header → старт со 2, headerless → со 1); headerless-колонки именуются `col_{i}`.
   Пустые строки источника **не пропускаются** — эмитятся как запись со всеми `None` с сохранением
   выравнивания `line_no` по физической строке.
5. **Поведение ошибок**: ошибки чтения/парсинга оборачиваются в `SOURCE_ERROR` существующей границей
   `Extractor` (гранулярность — в P-003).

---

## 🧪 Валидация решения

**Тесты (план)**:
- ✅ `unit`: `SourceAdapterRegistry` — выбор по `(type, format)`, стабильная ошибка для незарегистрированного ключа.
- ✅ `integration`: `PolarsCsvRecordSource` на реальном CSV в `tmp_path` — header/headerless, delimiter/encoding,
  null-паритет (`""`, `"null"`/`"NULL"`, пробелы), большой файл (bounded-memory через батчи), `record_id`/line_no.
- ✅ `unit` паритета: старый `parse_null` ↔ polars-путь до удаления старого кода.
- ✅ `architecture`: `connector.datasets.*` не импортирует `connector.infra.*` (после снятия `ignore_imports`).
- ✅ `e2e`/обновление fakes `DatasetSpec` (`get_source_spec`) в существующих тестах.

**Проверка статикой**:
1. `lint-imports` зелёный **без** `ignore_imports`.
2. `mypy connector/` — без ошибок на новых интерфейсах.
3. `ruff check` / `ruff format --check`.

**Метрики успеха**:
- Записей `ignore_imports` для sources: 0.
- Добавление гипотетического второго source-builder не требует правок `create()`/`datasets`/`domain`.

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- В объёме DEC-001 поддержан только `file/csv` (один зарегистрированный builder); полиморфный spec для
  db/api — P-002, внутренняя декомпозиция адаптера — P-003.
- Streaming path на `polars.scan_csv().collect_batches()` поддерживает только UTF-8-совместимые кодировки
  (`utf-8`, `utf-8-sig`). Произвольные Python-codec из `SourceSpec.encoding` требуют отдельной
  стратегии чтения в P-002/P-003.
- `record_id` остаётся позиционным (`line:{n}`) — контентный id вне объёма (P-003).
- Единый код ошибки `SOURCE_ERROR` — гранулярность откладывается до P-003.

**Явный scope-out — `SourceMapper`**:
`SourceMapper` (`domain/ports/transform/sources.py`) — это **живой порт map-стадии**, а не мёртвый код:
его наследует `MapperEngine(SourceMapper[...])` ([mapper_engine.py:26](../../../connector/domain/transform/mapping/mapper_engine.py)),
от него зависит `MapStage` ([stages.py:386](../../../connector/domain/transform/stages/stages.py)),
он покрыт тестами (`tests/unit/transform/test_source_mapper.py`). DEC-001 **не трогает** `SourceMapper`.
Любой пересмотр map-абстракции (в т.ч. соседство `RowSource`/`SourceMapper` в одном файле порта) —
предмет отдельного решения по mapping-contract, а не extract housekeeping. Фаза 0 ограничена правкой
устаревшей документации, ошибочно описывавшей CSV-источник как реализующий `SourceMapper`.

**Риски**:
- ⚠️ Регресс null-семантики при переходе на polars `null_values` → **Митигация**: unit-тесты паритета
  до удаления `parse_null`; покрыть пограничные кейсы.
- ⚠️ Рост пика памяти из-за eager-чтения → **Митигация**: `scan_csv().collect_batches()` по умолчанию;
  `read_batch_size` из конфига; smoke на большом CSV; дефолт (10k) финализировать бенчем.
- ⚠️ Смена Protocol `DatasetSpec` ломает потребителей/фейки → **Митигация**: греп `build_record_source`
  перед удалением; единственный реальный потребитель — `row_source`-провайдер; обновить fakes.
- ⚠️ line_no/header offset при батч-чтении → **Митигация**: сквозной счётчик в адаптере + тесты
  header/headerless.

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `Extractor` (`domain/transform/core/extractor.py`) | Нет | Принимает `RowSource` как раньше |
| `row_source`-провайдер (`containers.py`) | Переезд | Из `PipelineContainer` в `sources_container`, через реестр |
| `YamlDatasetSpec` / `DatasetSpec` Protocol | API | `build_record_source()` → `get_source_spec()` |
| Use-cases стадий (`mapping/normalize/enrich/match/resolve`) | Косвенное | Получают `row_source` как раньше (контракт `RowSource` не меняется) |
| Тесты с фейковым `DatasetSpec` | Обновление | Реализовать `get_source_spec()` вместо `build_record_source()` |
| `AppConfig` потребители | Доп. секция | Чтение `app_config.extract.read_batch_size` в `sources_container` |

---

## 📚 Документация

**Обновлено в рамках реализации**:
- ✅ `connector/infra/sources/README.md` — polars-адаптер (`scan_csv().collect_batches()`), реализует `RowSource`, `SourceAdapterRegistry`.
- ✅ `connector/delivery/cli/README.md` — `sources_container`.
- ✅ `connector/datasets/README.md` — «Extract source seam» (без `build_record_source`).
- ✅ `connector/domain/ports/transform/README.md`, `connector/infra/README.md` — `RowSource`/`PolarsCsvRecordSource`.
- ✅ `examples/configs/config_example.yml` — секция `extract`.

---

## 🔗 Связанные документы

- [EXTRACT-PROBLEM-001](./EXTRACT-PROBLEM-001-source-selection-hardcoded-and-cross-layer-coupling.md) — решаемая проблема
- [EXTRACT-PROBLEM-002](./EXTRACT-PROBLEM-002-non-polymorphic-source-spec.md) — полиморфный spec (P-002, следующая фаза)
- [EXTRACT-PROBLEM-003](./EXTRACT-PROBLEM-003-monolithic-source-adapter-no-isolation.md) — декомпозиция адаптера (P-003)
- [EXTRACT_REFACTOR_WORKNOTE](../../notes/extract/EXTRACT_REFACTOR_WORKNOTE.md) — детальный дизайн, разборы ОВ-1.1…1.5
- `connector/infra/dictionaries/` — эталон-паттерн (polars-чтение + DI-субконтейнер)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-06-15 | Решение предложено (дизайн в worknote, фазы 0–1) |
| 2026-06-15 | Открытые вопросы ОВ-1.1…1.5 закрыты; решение принято |
| 2026-06-15 | Реализовано (CS0–CS5). Streaming-примитив: `scan_csv().collect_batches()` (вместо deprecated `read_csv_batched`). Сохранение пустых строк источника зафиксировано тестом. |
