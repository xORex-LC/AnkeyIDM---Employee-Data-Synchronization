# connector/domain/ports/transform

## Назначение

Интерфейсы (порты) transform-конвейера: итерация строк источника, маппинг записи и справочники.

## Порты

| Файл | Порт | Назначение |
|---|---|---|
| `sources.py` | `RowSource` | Итерация строк источника: `__iter__() -> Iterable[SourceRecord]` (extract-seam) |
| `sources.py` | `SourceMapper[T]` | Порт map-стадии: `map(record: SourceRecord) -> TransformResult[T]` (сырьё → первая доменная строка) |
| `source_errors.py` | `SourceAdapterError`, `SourceReadError`, `SourceParseError` | Typed exceptions на границе `RowSource`: адаптер сообщает тип отказа, `Extractor` переводит его в diagnostics |
| `dictionaries.py` | `DictionaryProviderPort` | `lookup(key, field)`, `contains(key)`, `canonicalize(value)` — поиск в справочнике |

## Реализация

`RowSource` → `infra/sources/csv_reader.py` (`PolarsCsvRecordSource`)
`SourceReadError` / `SourceParseError` → выбрасываются source-адаптерами при stream-level отказе; `Extractor` классифицирует их как `SOURCE_READ_FAILED` / `SOURCE_PARSE_FAILED`, остальные исключения остаются fallback `SOURCE_ERROR`.
`SourceMapper` → `domain/transform/mapping/mapper_engine.py` (`MapperEngine`); потребитель — `MapStage` (`domain/transform/stages/stages.py`). Реализация map-порта живёт в `domain` (mapping — доменная DSL-логика), а не в `infra`.
`DictionaryProviderPort` → `infra/dictionaries/provider.py`

> Примечание: `RowSource` (extract) и `SourceMapper` (map) сейчас соседствуют в одном файле `sources.py`,
> хотя относятся к разным стадиям. Возможное расщепление по стадиям и ревизия map-абстракции
> (`Protocol` vs ABC, имя) — предмет отдельного mapping-contract решения, вне extract-рефактора
> (см. [EXTRACT worknote](../../../../docs/notes/extract/EXTRACT_REFACTOR_WORKNOTE.md)).
