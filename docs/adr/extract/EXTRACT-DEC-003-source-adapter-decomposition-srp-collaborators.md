# EXTRACT-DEC-003: SRP-декомпозиция source-адаптера на формат-агностичное ядро и формат-специфичный reader

> **Статус**: Принято
> **Дата принятия**: 2026-06-16
> **Решает проблему**: [EXTRACT-PROBLEM-003](./EXTRACT-PROBLEM-003-monolithic-source-adapter-no-isolation.md)
> **Участники решения**: @xORex-LC

---

## 📋 Контекст

После [EXTRACT-DEC-001](./EXTRACT-DEC-001-source-selection-seam-and-polars-csv-adapter.md)/[EXTRACT-DEC-002](./EXTRACT-DEC-002-polymorphic-source-spec-typed-format-blocks.md)
единственная реализация источника — `PolarsCsvRecordSource` (`infra/sources/csv/record_source.py`) на
`pl.scan_csv().collect_batches()`. Она по-прежнему совмещает несколько зон ответственности в одном модуле
(I/O+parse, декод колонок, сборка `SourceRecord`, null/str-политика, encoding), а классификация ошибок
отсутствует: любое исключение источника всплывает в `Extractor` и фиксируется единым `SOURCE_ERROR`
(IO_ERROR), поток рвётся ([EXTRACT-PROBLEM-003](./EXTRACT-PROBLEM-003-monolithic-source-adapter-no-isolation.md)).

Это блокирует переиспользование между будущими адаптерами (db/api) и выделение extract в пакет (цель #3).
Детальная карта ответственностей, разбор альтернатив и закрытые форки (ОВ-C1…C5) —
[EXTRACT_REFACTOR_WORKNOTE](../../notes/extract/EXTRACT_REFACTOR_WORKNOTE.md), раздел «Детальный дизайн — Фаза 3».

**Скоуп.** Решение покрывает **только внутреннюю декомпозицию** адаптера (Фаза 3). Выделение extract в
отдельный пакет на `uv` — отдельный **EXTRACT-DEC-004** (Фаза 4): границы сначала доказываются кодом, и
лишь затем фиксируются пакетной структурой. Полиморфизм spec уже закрыт DEC-002.

---

## 🎯 Решение

Разложить монолитный адаптер по оси **«формат-специфичное производство строк» vs «формат-агностичная
сборка `SourceRecord` + классификация ошибок»** — а не механическим 4-way Reader/Decoder/RecordBuilder/
ErrorClassifier (read+parse+decode слиты внутри polars `scan_csv`, отдельный Decoder был бы церемонией).

Состав решения:

1. **Доменный typed-exception contract** (`connector/domain/ports/transform/source_errors.py`):
   `SourceAdapterError` (база) → `SourceReadError` (I/O/файл/encoding), `SourceParseError` (битая
   структура). Это контракт **границы порта** `RowSource`: что реализация источника может бросить, а
   `Extractor` (domain) — поймать. **Живёт в domain**, потому что domain их ловит; разместить их в infra
   создало бы `domain → infra` импорт и нарушило import-linter («domain is the inner layer»).
2. **Формат-агностичное ядро** (`infra/sources/core/`, переиспользуется csv/db/api):
   - `ValueNormalizer` — null/str-политика (`""`/`null`→None, trim; контракт `str|None`);
   - `RecordIdStrategy` — стратегия id; дефолт `PositionalRecordIdStrategy` (`line:{n}`), extension point;
   - `RecordAssembler` — `(raw_row: Mapping, line_no) → SourceRecord` (применяет `ValueNormalizer` + `RecordIdStrategy`).
   (Импорт `infra → domain` разрешён, поэтому сотрудники ядра свободно используют доменные `SourceRecord`
   и typed-exceptions из п.1.)
3. **Формат-специфичный CSV-адаптер** (`infra/sources/csv/`):
   - `PolarsCsvFrameReader` — `scan_csv`/`collect_batches` + encoding + декод колонок (BOM/headerless `col_{i}`);
   - **`PolarsCsvErrorClassifier` (infra-local)** — типизирует **только известные** low-level ошибки в
     доменные: `OSError`/`UnicodeError` → `SourceReadError`; `polars.exceptions.PolarsError` →
     `SourceParseError`. `NoDataError` трактуется как `SourceParseError` (структурно пустой/нечитаемый
     как CSV источник). Encoding-policy — наш код, поэтому `_normalize_encoding` сразу бросает
     `SourceReadError`, без fragile matching по тексту `ValueError`. **Неизвестное не заворачивает**
     (`classify → None`), reader пробрасывает исходное исключение → срабатывает fallback `Extractor`
     (`SOURCE_ERROR`). Классификатор **infra/polars-специфичен**, поэтому живёт в адаптере, а не в `core`;
     формат-агностичный общий classifier — преждевременная абстракция, вводится при появлении второго адаптера.
   - `PolarsCsvRecordSource` — тонкая композиция `FrameReader → RecordAssembler`, реализует `RowSource`.
4. **Гранулярные коды ошибок** `SOURCE_READ_FAILED` (IO_ERROR) и `SOURCE_PARSE_FAILED` (DATA_INVALID) в
   `core_catalog.py`. `Extractor` ловит **только доменные** `SourceReadError`/`SourceParseError` и мапит их
   на каталог (адаптер не знает про `ErrorCatalog`); неожиданные исключения → fallback `SOURCE_ERROR`.
   Терминирование потока сохраняется (per-record recovery для polars batch-parse нереалистичен — отложен до
   построчных db/api-адаптеров).
5. **`record_id`** остаётся позиционным (`line:{n}`) дефолтом за `RecordIdStrategy`; контентный id — вне
   объёма (требует знания бизнес-ключа = семантика Map).
6. **`fields:` остаётся advisory** — никакой валидации записей в extract (тип→Normalize, nullability→
   Validate, наличие колонок уже ловит Map через `missing_source_column`).
7. **`str | None` — extract-boundary контракт для ВСЕХ источников.** `ValueNormalizer` фиксирует, что любой
   адаптер (csv/db/api) отдаёт raw-значения как `str | None` на границе extract; типизация (`int`/`bool`/
   дата) остаётся задачей **Normalize**. Это явный сквозной инвариант, а не CSV-частность.
8. **Package-aware раскладка** `core/` + `csv/` — чтобы DEC-004 поднял ядро/адаптер в пакет без переделок.
   Доменный `source_errors.py` остаётся в domain (граница), пакет-кандидат — только `infra/sources/*`.

---

## 🏗️ Архитектурное решение

### Компоненты

**Новый модуль (domain)** — `connector/domain/ports/transform/source_errors.py`:
- `SourceAdapterError` (база), `SourceReadError`, `SourceParseError` — контракт границы порта `RowSource`.

**Новые модули** (`connector/infra/sources/core/`, формат-агностично):
- `values.py` — `ValueNormalizer` (перенос текущего `_normalize_value`).
- `ids.py` — `RecordIdStrategy` (Protocol) + `PositionalRecordIdStrategy`.
- `assembler.py` — `RecordAssembler`.

**Новые модули** (`connector/infra/sources/csv/`, формат-специфично):
- `reader.py` — `PolarsCsvFrameReader` (перенос `_iter_batches`/`_normalize_columns`/`_normalize_encoding`).
- `errors.py` — `PolarsCsvErrorClassifier` (infra-local: polars/OS-исключения → доменные typed-exceptions).
- `record_source.py` — `PolarsCsvRecordSource` (композиция reader+assembler, реализует `RowSource`).
- `builder.py` — `build_csv_source` (перенос; контракт `(SourceSpec) → RowSource` неизменен).

**Изменяемые компоненты**:
- `connector/infra/sources/csv/` — новый пакет CSV-адаптера; переходный re-export `csv_reader.py`
  удалён в cleanup change-set'е.
- `connector/domain/transform/core/extractor.py` — ловит доменные `SourceReadError`/`SourceParseError` →
  `SOURCE_READ_FAILED`/`SOURCE_PARSE_FAILED`; fallback `Exception` → `SOURCE_ERROR`.
- `connector/domain/diagnostics/core_catalog.py` — `CatalogEntry("SOURCE_READ_FAILED", IO_ERROR)` и
  `CatalogEntry("SOURCE_PARSE_FAILED", DATA_INVALID)`.
- `connector/delivery/cli/sources_container.py` — сборка `PolarsCsvRecordSource` из новых сотрудников.

**Не меняются**: `SourceAdapterRegistry` (контракт `create(spec) → RowSource`, ключ `(type, format.kind)`),
`RowSource`/`SourceRecord` (domain), `SourceSpec`, `resolve_source_location`, словари.

> **Граница зависимостей.** Доменные typed-exceptions — в `domain`; `infra/sources/*` импортирует их из
> domain (`infra → domain` разрешён). Обратного импорта `domain → infra` нет — контракт import-linter
> «domain is the inner layer» сохраняется.

### Интерфейсы

```python
# domain/ports/transform/source_errors.py   ← КОНТРАКТ ГРАНИЦЫ ПОРТА (domain)
class SourceAdapterError(Exception): ...   # база
class SourceReadError(SourceAdapterError): ...    # I/O / файл / encoding
class SourceParseError(SourceAdapterError): ...   # битая структура источника

# infra/sources/core/values.py
class ValueNormalizer:
    def normalize(self, value: object) -> str | None: ...        # "" / "null" → None, trim, str

# infra/sources/core/ids.py
class RecordIdStrategy(Protocol):
    def record_id(self, *, line_no: int, raw_row: Mapping[str, object]) -> str: ...
class PositionalRecordIdStrategy:                                  # дефолт: f"line:{line_no}"
    def record_id(self, *, line_no: int, raw_row: Mapping[str, object]) -> str: ...

# infra/sources/core/assembler.py
class RecordAssembler:
    def __init__(self, *, values: ValueNormalizer, ids: RecordIdStrategy) -> None: ...
    def assemble(self, raw_row: Mapping[str, object], *, line_no: int) -> SourceRecord: ...

# infra/sources/csv/errors.py   ← infra-local, знает про polars
class PolarsCsvErrorClassifier:
    def classify(self, exc: Exception) -> SourceAdapterError | None: ...
    # ИЗВЕСТНЫЕ low-level → доменный typed-exception:
    #   OSError/UnicodeError → SourceReadError
    #   polars.exceptions.PolarsError → SourceParseError
    #   NoDataError → SourceParseError как структурно пустой/нечитаемый CSV
    # НЕИЗВЕСТНОЕ → None (classifier НЕ заворачивает насильно).
    # Encoding-policy бросает SourceReadError прямо в reader, без string matching ValueError.

# infra/sources/csv/reader.py
class PolarsCsvFrameReader:
    def iter_rows(self) -> Iterator[tuple[int, Mapping[str, object]]]: ...
        # батчи polars → (line_no, row-dict). Reader владеет line_no, потому что только он знает
        # header-offset и позицию строки внутри batched stream. При исключении:
        #   typed = classifier.classify(exc)
        #   raise typed from exc   если typed is not None   (доменный SourceReadError/SourceParseError)
        #   raise                  иначе                     (исходное исключение → Extractor fallback SOURCE_ERROR)

# infra/sources/csv/record_source.py
class PolarsCsvRecordSource:                                       # реализует RowSource
    def __iter__(self) -> Iterator[SourceRecord]: ...             # for line_no, row in reader.iter_rows(): assembler.assemble(row, line_no=line_no)

# domain/transform/core/extractor.py (изменение)
#   except SourceReadError  → SOURCE_READ_FAILED
#   except SourceParseError → SOURCE_PARSE_FAILED
#   except Exception        → SOURCE_ERROR (fallback)
```

### Поток данных

```
PolarsCsvFrameReader.iter_rows()  [scan_csv→collect_batches, encoding, BOM/headerless]
        │ polars/OS-исключения → PolarsCsvErrorClassifier (infra) → доменные SourceReadError | SourceParseError
        ▼ (line_no, row-dict)
RecordAssembler.assemble(row, line_no)  [ValueNormalizer + RecordIdStrategy] → SourceRecord
        ▼
Extractor.run()  →  TransformResult[None]
        └ except SourceReadError → SOURCE_READ_FAILED ; SourceParseError → SOURCE_PARSE_FAILED ;
          except Exception → SOURCE_ERROR (fallback)        [маппинг на ErrorCatalog — в domain]
```

---

## ✅ Почему это решение?

**Преимущества**:
- ✅ SRP: каждая зона ответственности — отдельный сотрудник; `PolarsCsvRecordSource` сводится к композиции.
- ✅ DRY/переиспользование: `RecordAssembler`/`ValueNormalizer`/`RecordIdStrategy` — формат-агностичны;
  будущие db/api реализуют только свой reader + свой infra-local classifier (типизирующий их низкоуровневые
  ошибки в общие доменные `SourceReadError`/`SourceParseError`).
- ✅ Гранулярная диагностика: `SOURCE_READ_FAILED` vs `SOURCE_PARSE_FAILED` вместо единого `SOURCE_ERROR`.
- ✅ Граница слоёв: адаптер не знает про `ErrorCatalog`; маппинг — в domain (`Extractor`).
- ✅ Package-aware: `core/` + `csv/` готовы к выносу в пакет (DEC-004) без переделок.
- ✅ Extension point `RecordIdStrategy` без протаскивания семантики полей в extract.

**Недостатки (компромиссы)**:
- ⚠️ Больше модулей/классов для одного CSV-адаптера сейчас (но это и есть подготовка к много-адаптерности
  и упаковке; ядро переиспользуемо).
- ⚠️ Per-record recovery не вводится (ограничение polars batch-parse) — терминирование сохраняется;
  механизм закладывается, но реализуется с первым построчным адаптером.
- ✅ Переходный re-export `csv_reader.py` удалён после обновления импортов в code/tests.

**Альтернативы, которые отклонили**:
- ❌ **Строгий 4-way Reader/Decoder/RecordBuilder/ErrorClassifier**: для polars read+parse слиты в
  `scan_csv` — отдельный Decoder = искусственная церемония (KISS).
- ❌ **Контентный/бизнес-ключевой `record_id` сейчас**: требует знания ключа = семантика Map, нарушает
  границу extract; пересекается с Map.
- ❌ **Валидация записей по `fields:` в extract**: тип→Normalize, nullability→Validate, наличие колонок
  уже ловит Map (`missing_source_column`); `SourceFieldSpec` рантайм-неиспользуем. «fields как source
  schema contract» — отдельное будущее решение.
- ❌ **Классификация ошибок прямо в адаптере (с кодами каталога)**: адаптер не должен знать про
  `ErrorCatalog` (domain); адаптер кидает типизированные доменные исключения, маппит `Extractor`.
- ❌ **Typed-exceptions в `infra/sources/core`**: их ловит `Extractor` (domain) → возник бы запрещённый
  импорт `domain → infra`. Контракт исключений принадлежит **domain** (граница порта `RowSource`).
- ❌ **Формат-агностичный `SourceErrorClassifier` в `core/` сейчас**: преждевременная абстракция —
  классификация polars-специфична. Для DEC-003 достаточно доменных exception-типов + infra-local
  `PolarsCsvErrorClassifier`; общий classifier — когда появится второй адаптер.
- ❌ **Попытка per-record recovery для CSV сейчас**: polars batch-parse all-or-nothing — нереалистично.
- ❌ **Упаковка в пакет в рамках DEC-003**: границы сначала доказываются кодом (вынесено в DEC-004).

---

## 🛠️ Реализация

> Разбивка на change-set'ы — в [EXTRACT_DEC_003_IMPLEMENTATION_PLAN](../../notes/extract/EXTRACT_DEC_003_IMPLEMENTATION_PLAN.md). Здесь — состав и инварианты.

### Ключевые файлы

| Файл | Изменение |
|------|-----------|
| `connector/domain/ports/transform/source_errors.py` | **Создан (domain)**: `SourceAdapterError`/`SourceReadError`/`SourceParseError` |
| `connector/infra/sources/core/values.py` | Создан `ValueNormalizer` |
| `connector/infra/sources/core/ids.py` | Создан `RecordIdStrategy` + `PositionalRecordIdStrategy` |
| `connector/infra/sources/core/assembler.py` | Создан `RecordAssembler` |
| `connector/infra/sources/csv/reader.py` | `PolarsCsvFrameReader` (из `_iter_batches`/`_normalize_columns`/`_normalize_encoding`) |
| `connector/infra/sources/csv/errors.py` | **Создан** `PolarsCsvErrorClassifier` (infra-local; polars/OS → доменные typed-exceptions) |
| `connector/infra/sources/csv/record_source.py` | `PolarsCsvRecordSource` (композиция reader+assembler) |
| `connector/infra/sources/csv/builder.py` | `build_csv_source` (перенос) |
| `connector/infra/sources/csv/` | CSV adapter package: reader, classifier, record source, builder |
| `connector/domain/transform/core/extractor.py` | `except SourceReadError/SourceParseError` → гранулярные коды; fallback → `SOURCE_ERROR` |
| `connector/domain/diagnostics/core_catalog.py` | `SOURCE_READ_FAILED` (IO_ERROR), `SOURCE_PARSE_FAILED` (DATA_INVALID) |
| `connector/delivery/cli/sources_container.py` | Сборка адаптера из сотрудников ядра |
| `connector/infra/sources/README.md`, `connector/domain/ports/transform/README.md` | Раскладка `core/`+`csv/`; typed-exception contract порта |
| `tests/unit/...`, `tests/integration/...` | Юниты сотрудников + классификатора + тесты паритета контрактов |

### Инварианты

1. **Контракты сохраняются 1:1**: `values: str|None`; null = trim + (`""`/`null` case-insensitive)→None;
   `line_no` header→2/headerless→1, == физической строке; `record_id="line:{n}"`; headerless→`col_{i}`;
   BOM снимается только с первого заголовка; пустые строки источника не пропускаются.
2. **Направление зависимостей**: typed-exception contract — в `domain`; `infra/sources/*` импортирует его
   из domain (`infra → domain` ок), `domain → infra` отсутствует; адаптер не знает про `ErrorCatalog`.
3. **`str | None` — extract-boundary контракт для всех адаптеров** (csv/db/api); типизация — в Normalize.
4. **Шов DEC-001/002 неизменен**: `SourceAdapterRegistry.create(spec)→RowSource`, ключ `(type, format.kind)`.
5. **`RowSource`/`SourceRecord` (domain)** не меняются.
6. **Декомпозиция, не переписывание**: логика переносится в сотрудников, поведение тождественно (parity-тесты).

---

## 🧪 Валидация решения

**Тесты (план)**:
- ✅ `unit`: `ValueNormalizer` — `""`/`" null "`/`"NULL"`/`"0"`/`None`.
- ✅ `unit`: `PositionalRecordIdStrategy` — `line:{n}` для header/headerless стартов.
- ✅ `unit`: `RecordAssembler` — сборка `SourceRecord` из row-dict (id/values/line_no).
- ✅ `unit`: `PolarsCsvErrorClassifier` — отображение polars/OS-исключений в доменные `SourceReadError`/`SourceParseError`.
- ✅ `unit`: `Extractor` — `SourceReadError`→`SOURCE_READ_FAILED`, `SourceParseError`→`SOURCE_PARSE_FAILED`,
  прочее → `SOURCE_ERROR` (без регресса).
- ✅ `integration`/parity: `PolarsCsvRecordSource` на реальном CSV в `tmp_path` даёт **идентичный** поток
  `SourceRecord`, что и до декомпозиции (header/headerless/null/BOM/большой файл/битый файл).
- ✅ `architecture`: границы слоёв (`lint-imports`) не нарушены; `infra/sources` не зависит от domain-каталога ошибок сверх допустимого.

**Проверка статикой**: `ruff`, `mypy` (новые модули), `lint-imports`, целевой `pytest`.

**Метрики успеха**:
- Полный прогон `employees`/`organizations` (`mapping`/`import plan`) — без изменений вывода.
- Сбойный источник даёт `SOURCE_READ_FAILED`/`SOURCE_PARSE_FAILED` (а не единый `SOURCE_ERROR`).

---

## ⚠️ Риски и ограничения

**Известные ограничения**:
- Per-record recovery не реализован (ограничение polars batch-parse); терминирование потока сохраняется.
- `record_id` остаётся позиционным; контентный id — будущее решение.
- `fields:` остаётся advisory; «source schema contract» — вне объёма.
- **Edge read/parse**: реальные битые UTF-8 байты polars поднимает как `ComputeError`(⊂`PolarsError`) →
  классифицируются как `SOURCE_PARSE_FAILED`, а не `SOURCE_READ_FAILED` (надёжно различить без fragile
  string-matching нельзя — принято осознанно; зафиксировано в docstring `PolarsCsvErrorClassifier`).
- **`topology_bootstrap`/`PolarsSourceAdjacencyReader` — второй CSV-потребитель — вне объёма DEC-003.**
  DEC-003 декомпозирует именно extract-source-адаптер; топология читает adjacency отдельно. Переиспользование
  `PolarsCsvFrameReader`/column-policy там — желательный follow-up (DRY), но осознанно отложено, чтобы не
  раздувать blast radius; зафиксировано как явный форвард (кандидат к DEC-004 или отдельному рефактору).

**Риски**:
- ⚠️ Регресс контрактов при переносе логики → **Митигация**: parity-тесты до/после; перенос без изменения поведения.
- ✅ Переходный re-export `csv_reader.py` не стал permanent compatibility debt: cleanup change-set
  обновляет imports в code/tests и удаляет модуль совместимости.
- ⚠️ Неверная классификация polars-исключений (read vs parse) → **Митигация**: `PolarsCsvErrorClassifier`
  (infra-local) с тестами на типовые исключения; **неизвестное не заворачивается** (`classify → None`,
  reader пробрасывает исходное) → детерминированный fallback `Extractor` (`SOURCE_ERROR`).
- ⚠️ Дрейф CSV-политики между extract-адаптером и `topology_bootstrap` (две реализации чтения CSV) →
  **Митигация**: зафиксировать как явный форвард на переиспользование `PolarsCsvFrameReader`; до тех пор
  держать column/null-политику в одном месте (`core`/`csv`) и ссылаться на неё в follow-up.
- ⚠️ Рост числа модулей усложняет навигацию → **Митигация**: README раскладки `core/`+`csv/`.

---

## 🔄 Влияние на другие компоненты

| Компонент | Влияние | Требуемые изменения |
|-----------|---------|---------------------|
| `domain/ports/transform/` | Прямое | Новый `source_errors.py` (контракт границы порта) |
| `Extractor` (domain) | Прямое | `except` доменных typed-exceptions → гранулярные коды; fallback `SOURCE_ERROR` |
| `core_catalog.py` | Прямое | Новые `CatalogEntry` (read/parse) |
| `sources_container.py` | Минимальное | Сборка `PolarsCsvRecordSource` из сотрудников |
| `SourceAdapterRegistry` | Нет | Контракт/ключ неизменны |
| `RowSource`/`SourceRecord` | Нет | Контракты стабильны |
| `topology_bootstrap`/`PolarsSourceAdjacencyReader` | **Вне объёма** | Форвард: переиспользование `PolarsCsvFrameReader` — отдельный follow-up |
| Тесты/фикстуры | Обновление | Юниты сотрудников + классификатора + parity |

---

## 📚 Документация

**Обновлено при реализации**:
- ✅ `connector/infra/sources/README.md` — раскладка `core/`+`csv/`, роли сотрудников.
- ✅ `connector/infra/sources/core/README.md` — формат-агностичное ядро сборки `SourceRecord`.
- ✅ `connector/infra/sources/csv/README.md` — CSV reader/classifier/record source и границы ответственности.
- ✅ `connector/domain/ports/transform/README.md` — typed-exception contract источников.
- ✅ `connector/domain/diagnostics/core_catalog.py` — коды `SOURCE_READ_FAILED`/`SOURCE_PARSE_FAILED`.
- ✅ [worknote](../../notes/extract/EXTRACT_REFACTOR_WORKNOTE.md) — детальный дизайн Фазы 3, закрытые ОВ-C1…C5.

---

## 🔗 Связанные документы

- [EXTRACT-PROBLEM-003](./EXTRACT-PROBLEM-003-monolithic-source-adapter-no-isolation.md) — решаемая проблема
- [EXTRACT-DEC-001](./EXTRACT-DEC-001-source-selection-seam-and-polars-csv-adapter.md) — шов выбора + polars-адаптер
- [EXTRACT-DEC-002](./EXTRACT-DEC-002-polymorphic-source-spec-typed-format-blocks.md) — полиморфный spec
- [EXTRACT_REFACTOR_WORKNOTE](../../notes/extract/EXTRACT_REFACTOR_WORKNOTE.md) — дизайн Фазы 3, разбор ОВ-C1…C5
- `connector/infra/dictionaries/` — эталон разделения чтения и хранения (loader vs backend)

---

## 📝 История

| Дата | Событие |
|------|---------|
| 2026-06-15 | Проблема зафиксирована ([EXTRACT-PROBLEM-003](./EXTRACT-PROBLEM-003-monolithic-source-adapter-no-isolation.md)) |
| 2026-06-16 | Дизайн проработан (сверка с polars-кодом); закрыты ОВ-C1…C5; скоуп = только декомпозиция |
| 2026-06-16 | Решение принято |
| 2026-06-16 | Ревью-правка: typed-exception contract перенесён в **domain** (`ports/transform/source_errors.py`) — иначе `domain → infra`; classifier сделан infra-local (`PolarsCsvErrorClassifier`); зафиксированы `str\|None` для всех источников, плановое снятие re-export, topology — вне объёма |
| 2026-06-16 | Реализация DEC-003 завершена: source core/csv packages, granular diagnostics, cleanup старого `csv_reader.py`, финальный checkup |
