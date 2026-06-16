# connector/infra/sources/csv

## Назначение

CSV/Polars adapter package для extract source seam. Пакет содержит только формат-специфичную
часть: чтение CSV, нормализацию колонок, владение физическим `line_no` и классификацию
Polars/OS ошибок в доменные source exceptions.

## Файлы

| Файл | Назначение |
|---|---|
| `reader.py` | `PolarsCsvFrameReader` — `scan_csv().collect_batches()` → `(line_no, raw_row)` |
| `errors.py` | `PolarsCsvErrorClassifier` — `OSError`/`UnicodeError` → `SourceReadError`, `PolarsError` → `SourceParseError` |
| `record_source.py` | `PolarsCsvRecordSource` — композиция reader + `RecordAssembler` |
| `builder.py` | `build_csv_source` — `SourceSpec` + runtime knobs → `PolarsCsvRecordSource` |

## Границы

`csv/` знает про `polars` и CSV-физику, но не знает про `ErrorCatalog`, downstream-стадии
и бизнес-семантику колонок. Значения и `record_id` собираются через `infra/sources/core`.

`connector/infra/sources/csv_reader.py` временно остаётся thin re-export для старых импортов.
