# connector/infra/sources

## Назначение

Чтение данных из источника и выдача строк как `SourceRecord`. Модуль реализует порт **`RowSource`**
(extract-seam: итерация строк источника), а **не** map-порт `SourceMapper`. Текущая реализация — CSV
на `polars.scan_csv().collect_batches()` (streaming, bounded-memory).

В рамках `EXTRACT-DEC-001` выбор источника вынесен в `SourceAdapterRegistry`, а composition root
регистрирует текущий CSV-builder явно. Размер батча чтения задаётся операционным параметром
`AppConfig.extract.read_batch_size` и прокидывается в builder через DI-замыкание.

## Файлы

| Файл | Назначение |
|---|---|
| `factory.py` | `SourceAdapterRegistry` и `SourceBuilder` — выбор `RowSource` по ключу `(source.type, source.format.kind)` |
| `core/` | Формат-агностичные сотрудники: `ValueNormalizer`, `RecordIdStrategy`, `RecordAssembler` |
| `csv/` | CSV/Polars adapter package: `PolarsCsvFrameReader`, `PolarsCsvErrorClassifier`, `PolarsCsvRecordSource`, `build_csv_source` |

## Зависимости

**Зависит от:** `polars`; `domain/transform/core/source_record.py` (контракт `SourceRecord`);
`domain/ports/transform/sources.py` (`RowSource`); `domain/ports/transform/source_errors.py`;
`domain/transform_dsl/specs` (`SourceSpec`).
**Используется:** `delivery/cli/sources_container.py` через `SourceAdapterRegistry`.

## Правило

Domain и usecases работают с `dict` / `SourceRecord`, не со специфичными для источника объектами.
`polars` DataFrame создаётся только здесь, в `infra/`, и не пересекает границу `RowSource`.

## Ограничения

Streaming-ридер Polars в текущем adapter path поддерживает только UTF-8-совместимые кодировки
(`utf-8`, `utf-8-sig`). Источники с другими Python-codec требуют отдельной стратегии чтения в рамках
следующих решений по source-spec/source-adapter декомпозиции.
