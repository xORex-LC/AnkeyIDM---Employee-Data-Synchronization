# connector/infra/sources

## Назначение

Чтение данных из источника и выдача строк как `SourceRecord`. Модуль реализует порт **`RowSource`**
(extract-seam: итерация строк источника), а **не** map-порт `SourceMapper`. Текущая реализация — CSV
на stdlib `csv`.

В рамках `EXTRACT-DEC-001` выбор источника вынесен в `SourceAdapterRegistry`, а composition root
регистрирует текущий CSV-builder явно. Backend пока остаётся stdlib `csv`; миграция чтения на polars
идёт отдельным change-set.

## Файлы

| Файл | Назначение |
|---|---|
| `factory.py` | `SourceAdapterRegistry` и `SourceBuilder` — выбор `RowSource` по ключу `(source.type, source.format)` |
| `csv_reader.py` | `CsvRecordSource` — реализует `RowSource`: читает CSV через stdlib `csv` (`DictReader` / headerless `reader`), итерирует строки как `SourceRecord`; учитывает `delimiter`, `encoding`, null-нормализацию |
| `csv_utils.py` | `CsvFormatError` (структурная ошибка CSV: количество колонок и т.п.) и `parse_null` (пустые/`"null"` → `None`, trim) |

## Зависимости

**Зависит от:** stdlib `csv`; `domain/transform/core/source_record.py` (контракт `SourceRecord`);
`domain/ports/transform/sources.py` (`RowSource`); `domain/transform_dsl/specs` (`SourceSpec`).
**Используется:** `delivery/cli/sources_container.py` через `SourceAdapterRegistry`.

## Правило

Domain и usecases работают с `dict` / `SourceRecord`, не со специфичными для источника объектами.
(После миграции на polars по EXTRACT-DEC-001 действует общее правило: polars DataFrame создаётся
только здесь, в `infra/`.)
