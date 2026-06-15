# EXTRACT-PROBLEM-001: Выбор источника захардкожен на CSV и завязан на infra через cross-layer импорт

> **Статус**: Решена в [EXTRACT-DEC-001](./EXTRACT-DEC-001-source-selection-seam-and-polars-csv-adapter.md)
> **Дата создания**: 2026-06-15
> **Затронутые компоненты**: `YamlDatasetSpec.build_record_source`, `CsvRecordSource`, `DatasetSpec` (Protocol), `connector/datasets/yaml_spec.py`, `delivery/cli/containers.py` (`row_source`)

---

## 📋 Контекст

Extract-стадия спроектирована источник-агностично на доменном уровне: `Extractor`
(`domain/transform/core/extractor.py`) принимает любой `RowSource` (Protocol,
`domain/ports/transform/sources.py`) и оборачивает `SourceRecord` в `TransformResult[None]`,
не зная ни формата, ни природы источника. Это корректный «шов» для подключения произвольных
источников (CSV, SQL/NoSQL, HTTP API).

Однако выбор и создание конкретной реализации источника происходит не на доменном шве, а в
`YamlDatasetSpec.build_record_source()` (`connector/datasets/yaml_spec.py`), который вызывается
DI-провайдером `row_source` (`delivery/cli/containers.py`).

---

## ⚠️ Проблема

`build_record_source()` жёстко завязан на единственную реализацию источника:

1. **Хардкод типа/формата**: метод выбрасывает `ValueError`, если
   `source.type != "file" or source.format != "csv"` — любой не-CSV источник невозможен в рантайме,
   несмотря на то что DSL-схема `SourceConfig` уже допускает `type: file|db|api`.
2. **Прямой импорт infra из datasets-слоя**: `from connector.infra.sources.csv_reader import CsvRecordSource`
   и прямая инстанциация конкретного адаптера внутри `datasets`-слоя.
3. **Нет реестра/фабрики источников**: соответствие «(type, format) → реализация `RowSource`»
   нигде не выражено; добавление нового источника требует правки тела `build_record_source()`.

Импорт #2 — известный технический долг, явно занесённый в `ignore_imports` в `pyproject.toml`
(`connector.datasets.yaml_spec -> connector.infra.sources.csv_reader`), что ослабляет
import-boundary-контракты (`domain`/`usecases` косвенно зависят от `infra`).

---

## 🔍 Симптомы

- **Симптом 1**: Чтобы добавить источник `db`/`api`, нужно править ядро выбора (`build_record_source`)
  и добавлять новый infra-импорт — нарушение OCP.
- **Симптом 2**: В `pyproject.toml` живёт постоянный `ignore_imports` для обхода правила
  «`datasets`/`domain` не зависят от `infra`».
- **Симптом 3**: DSL-схема `SourceConfig.type = Literal["file","db","api"]` декларирует поддержку
  трёх типов, но рантайм honors только `file/csv` (схема опережает реализацию).

---

## 📊 Масштаб проблемы

- **Частота**: При каждом добавлении нового типа/формата источника.
- **Критичность**: Высокая — блокирует ключевую цель «extract источник-агностичен и масштабируем».
- **Затронуто**: Все будущие датасеты с не-CSV источниками; чистота import-boundary всего проекта.

---

## 🧪 Как воспроизвести

1. Описать датасет с `source.type: db` (или `api`) в `source.yaml`.
2. Запустить любую pipeline-команду (`mapping`/`import plan`/...).
3. **Ожидаемый результат**: extract читает источник через соответствующий адаптер.
4. **Фактический результат**: `ValueError: <dataset> source spec must be file/csv for current runtime`
   из `YamlDatasetSpec.build_record_source()`.

---

## 🚫 Почему это проблема?

- Нарушается источник-агностичность extract: знание о конкретном источнике протекает в `datasets`-слой.
- Нарушается OCP: расширение требует правки существующего кода, а не добавления нового адаптера.
- Ослаблен import-boundary-контракт (постоянный `ignore_imports`), что подрывает гексагональную модель.
- Цель «гладкое масштабирование источников» недостижима без выделенного шва выбора.

---

## 💡 Возможные решения

> Детальный разбор и сравнение — в worknote
> [EXTRACT_REFACTOR_WORKNOTE](../../notes/extract/EXTRACT_REFACTOR_WORKNOTE.md).

### Вариант 1: Реестр/фабрика источников + wiring в composition root

- **Идея**: Ввести `SourceFactory`/registry по ключу `(type, format) → RowSource`. Перенести выбор и
  инстанциацию infra-адаптера в composition root (`delivery/cli/containers.py`); `datasets`-слой
  отдаёт только `SourceSpec`. Снять `ignore_imports`.
- **Плюсы**: OCP, чистый import-boundary, добавление источника = регистрация адаптера.
- **Минусы**: Нужен контракт фабрики и точка регистрации адаптеров.

### Вариант 2: Оставить выбор в `datasets`, но за абстракцией

- **Идея**: Спрятать `CsvRecordSource` за локальным фабричным методом внутри `datasets`.
- **Плюсы**: Меньше перемещений кода.
- **Минусы**: Не снимает cross-layer импорт infra и `ignore_imports`; долг остаётся.

---

## 🔗 Связанные документы

- [EXTRACT-PROBLEM-002](./EXTRACT-PROBLEM-002-non-polymorphic-source-spec.md) — неполиморфный spec источника
- [EXTRACT-PROBLEM-003](./EXTRACT-PROBLEM-003-monolithic-source-adapter-no-isolation.md) — монолитный адаптер
- [EXTRACT_REFACTOR_WORKNOTE](../../notes/extract/EXTRACT_REFACTOR_WORKNOTE.md) — анализ и дорожная карта
- `connector/datasets/yaml_spec.py` — `build_record_source()`
- `connector/domain/transform/core/extractor.py` — `Extractor` (источник-агностичное ядро)
- `connector/domain/ports/transform/sources.py` — `RowSource` (Protocol)
- `pyproject.toml` — `ignore_imports` для `datasets.yaml_spec -> infra.sources.csv_reader`

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-06-15 | Проблема зафиксирована |
| 2026-06-15 | Решение принято в [EXTRACT-DEC-001](./EXTRACT-DEC-001-source-selection-seam-and-polars-csv-adapter.md) |
