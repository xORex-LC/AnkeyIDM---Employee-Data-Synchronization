# connector/infra/sources/core

## Назначение

Формат-агностичное ядро source-адаптеров. Пакет получает raw-row от конкретного reader
и собирает доменный `SourceRecord`, сохраняя общий extract-boundary контракт `str | None`.

## Файлы

| Файл | Назначение |
|---|---|
| `values.py` | `ValueNormalizer` — trim + null-token policy (`""`/`null` → `None`) |
| `ids.py` | `RecordIdStrategy`, `PositionalRecordIdStrategy` — формирование `record_id` без бизнес-полей |
| `assembler.py` | `RecordAssembler` — `Mapping[str, object]` + `line_no` → `SourceRecord` |

## Границы

Пакет не читает файлы, не импортирует `polars`, не знает про CSV/header/headerless и не валидирует
`fields:` из source DSL. Наличие колонок остаётся ответственностью Map, типизация — Normalize,
структурный разбор формата — конкретного adapter package.
