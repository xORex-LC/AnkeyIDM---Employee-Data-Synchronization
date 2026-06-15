# EXTRACT-PROBLEM-002: Spec источника не полиморфен по типу — db/api непредставимы в рантайме

> **Статус**: Открыта
> **Дата создания**: 2026-06-15
> **Затронутые компоненты**: `SourceConfig`, `CsvSourceOptions`, `SourceFieldSpec`, `SourceSpec`, `resolve_source_location`, `connector/domain/transform_dsl/specs/source.py`, `connector/domain/transform_dsl/loader.py`

---

## 📋 Контекст

Конфигурация источника описывается декларативно в `datasets/<dataset>/source/source.yaml` и
валидируется Pydantic-моделью `SourceConfig` (`domain/transform_dsl/specs/source.py`).
`SourceConfig.type` уже объявлен как `Literal["file","db","api"]`, есть поля `format`, `location`,
`options`, `fields`. Резолв физического расположения выполняет `resolve_source_location()`
(`domain/transform_dsl/loader.py`).

---

## ⚠️ Проблема

Spec источника моделирует только файловый CSV-случай, а не семейство источников:

1. **`options` — нетипизированный `dict`, интерпретируемый только как CSV**: метод `csv_options()`
   валидирует `options` как `CsvSourceOptions` (delimiter/encoding). Для `db` (dsn/query/таймауты)
   или `api` (endpoint/auth/пагинация) типизированной формы нет.
2. **Валидатор форсит CSV-семантику**: `_validate_format_options` вызывает `csv_options()` для
   `format == "csv"` и требует `location` для `type == "file"`; для `db`/`api` нет ни валидации
   обязательных полей, ни структуры options.
3. **`resolve_source_location` ориентирован на файловый путь**: file-ветка резолвит путь через
   `source_data_root`; для `db`/`api` «location» (DSN/endpoint) не имеет отдельной модели резолва.
4. **`SourceFieldSpec` — документация, а не контракт**: по docstring `name`/`aliases` сейчас не
   применяются в рантайме (нет валидации схемы/типов на границе extract).

Итог: даже если шов выбора источника был бы готов (см.
[EXTRACT-PROBLEM-001](./EXTRACT-PROBLEM-001-source-selection-hardcoded-and-cross-layer-coupling.md)),
описать db/api-источник типобезопасно в spec невозможно.

---

## 🔍 Симптомы

- **Симптом 1**: Нет способа задать `db`/`api`-параметры (dsn, query, endpoint, auth) в типизированном виде.
- **Симптом 2**: Любые «чужие» ключи в `options` для CSV отклоняются (`DslBaseModel`, `extra="forbid"`),
  а для db/api — некуда складывать без разрушения инварианта строгой схемы.
- **Симптом 3**: `fields:` в `source.yaml` присутствует, но не участвует в рантайм-валидации записей.

---

## 📊 Масштаб проблемы

- **Частота**: При добавлении любого не-файлового или не-CSV источника.
- **Критичность**: Высокая — без полиморфного spec невозможно декларативно описать новые источники.
- **Затронуто**: DSL source-слой, loader (резолв location/connection), будущие db/api-адаптеры.

---

## 🧪 Как воспроизвести

1. Добавить в `source.yaml` секцию `source.type: db` с `options: {dsn: ..., query: ...}`.
2. Загрузить spec датасета.
3. **Ожидаемый результат**: типизированная валидация db-параметров.
4. **Фактический результат**: нет модели для db-options; валидатор не покрывает db/api, а CSV-путь к
   ним неприменим — параметры остаются непроверенным `dict[str, Any]` либо ломают строгую схему.

---

## 🚫 Почему это проблема?

- Декларативность источника неполна: схема не отражает реально поддерживаемое семейство источников.
- Невозможно дать типобезопасные и валидируемые настройки для db/api (риск runtime-ошибок).
- Блокирует цель «масштабирование источников гладко» на уровне конфигурации, а не только кода.

---

## 💡 Возможные решения

> Детальный разбор — в worknote
> [EXTRACT_REFACTOR_WORKNOTE](../../notes/extract/EXTRACT_REFACTOR_WORKNOTE.md).

### Вариант 1: Discriminated union по `type`/`format`

- **Идея**: Сделать `SourceConfig` полиморфным: per-type options-модели (`CsvSourceOptions`,
  `DbSourceOptions`, `ApiSourceOptions`) через discriminated union; резолв location/connection —
  per-type (расширение `resolve_source_location` или резолвер на адаптер).
- **Плюсы**: Типобезопасность, валидация per-type, расширяемость без `dict[str, Any]`.
- **Минусы**: Рефактор spec-модели и loader; миграция существующего CSV-spec.

### Вариант 2: Плоская схема + ad-hoc валидация в адаптере

- **Идея**: Оставить `options: dict`, валидировать внутри каждого адаптера.
- **Плюсы**: Минимум изменений в DSL.
- **Минусы**: Теряется декларативная валидация на границе DSL; дублирование проверок по адаптерам.

---

## 🔗 Связанные документы

- [EXTRACT-PROBLEM-001](./EXTRACT-PROBLEM-001-source-selection-hardcoded-and-cross-layer-coupling.md) — шов выбора источника
- [EXTRACT_REFACTOR_WORKNOTE](../../notes/extract/EXTRACT_REFACTOR_WORKNOTE.md) — анализ и дорожная карта
- `connector/domain/transform_dsl/specs/source.py` — `SourceConfig`, `CsvSourceOptions`, `SourceFieldSpec`
- `connector/domain/transform_dsl/loader.py` — `resolve_source_location`
- `datasets/employees/source/source.yaml` — текущий пример source-spec

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-06-15 | Проблема зафиксирована |
