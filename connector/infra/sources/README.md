# connector/infra/sources

## Назначение

Чтение данных из источника и выдача строк как `SourceRecord`. Модуль реализует порт **`RowSource`**
(extract-seam: итерация строк источника), а **не** map-порт `SourceMapper`. Текущая реализация — CSV
на stdlib `csv`.

> Планируется (см. [EXTRACT-DEC-001](../../../docs/adr/extract/EXTRACT-DEC-001-source-selection-seam-and-polars-csv-adapter.md)):
> миграция CSV-чтения на polars и выбор источника через `SourceAdapterRegistry` в composition root.
> README будет обновлён при реализации.

## Файлы

| Файл | Назначение |
|---|---|
| `csv_reader.py` | `CsvRecordSource` — реализует `RowSource`: читает CSV через stdlib `csv` (`DictReader` / headerless `reader`), итерирует строки как `SourceRecord`; учитывает `delimiter`, `encoding`, null-нормализацию |
| `csv_utils.py` | `CsvFormatError` (структурная ошибка CSV: количество колонок и т.п.) и `parse_null` (пустые/`"null"` → `None`, trim) |

## Зависимости

**Зависит от:** stdlib `csv`; `domain/transform/core/source_record.py` (контракт `SourceRecord`);
структурно удовлетворяет порту `RowSource` из `domain/ports/transform/sources.py`.
**Используется:** `datasets/yaml_spec.py` (через `DatasetSpec.build_record_source()`).

## Правило

Domain и usecases работают с `dict` / `SourceRecord`, не со специфичными для источника объектами.
(После миграции на polars по EXTRACT-DEC-001 действует общее правило: polars DataFrame создаётся
только здесь, в `infra/`.)
