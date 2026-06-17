# ECS Logging — Worknote (журнал решений и навигация)

Статус: living hub · Последнее обновление: 2026-06-15

## Цель документа

Узкий хаб ECS-перехода логирования: **журнал решений + указатели**. Принятые архитектурные решения
живут в [OBSERVABILITY-DEC-003](../../adr/observability/OBSERVABILITY-DEC-003-ecs-renderer-and-field-mapping.md),
семантика — в dev-docs/taxonomy YAML, проектирование текущей фазы — в
[phase-2-design.md](./phase-2-design.md), замороженные планы прошлых фаз — в [archive/](./archive/).
Здесь намеренно **нет копии** контракта/границ/инвариантов — только то, что ещё не принято, и история.

Навигация по папке — [README.md](./README.md).

---

## Уже зафиксировано (контекст, детали — в ADR)

- Один процессор `ecs_transform` (dict→dict) перед `JSONRenderer`, только на JSON-синках.
- Порядок: `ExceptionRenderer → redaction → remove_processors_meta → ecs_transform → JSONRenderer`.
- Dotted-ключи; catch-all неучтённого в `labels.*`.
- Машинная истина taxonomy — YAML в `connector/common/observability/taxonomy/`
  (`actions.yaml`, `fields/*.yaml`); семантика — `docs/dev/layers/observability/ecs-logging-taxonomy/`.
- `connector/infra/logging/ecs.py` — runtime-маппер в ECS-форму, не каталог taxonomy.
- Production formatter свой (`ecs_transform`); `ecs-logging` — только как справочный/dev-инструмент.
- Контракт события (`ObservabilityEvent`), границы слоёв, reserved keys/roots, error precedence,
  pydantic-политика — **приняты, см. ADR** (§Event contract, §Архитектурные границы, §Pydantic).

## Открытые вопросы

Открытые решения и триаж тем перенесены в [phase-2-design.md](./phase-2-design.md) (форки A–F + темы
2/3/6/8/9/11/12/13). Здесь не дублируются.

---

## Журнал решений

| Дата | Тема | Решение |
|------|------|---------|
| 2026-06-09 | — | Worknote заведён; темы 1–12 поставлены на обсуждение |
| 2026-06-09 | Тема 10 | Закрыта: `LegacyCompatibleStructlogLogger` удалён в `82ae47b` (Stage Z); адаптера нет. Выявлен doc drift в `observability-logging.md` + skill |
| 2026-06-10 | Тема 1 | RESOLVED: `component` — только из контекста (per-process = партиция файла); доступ к подсистеме → `scope=<subsystem>` (прецедент cache/vault). Правки call-sites (vault-usecase/dictionary/obs_artifacts) + reserved-ключ в `ecs_transform` + guard-тест. Dictionary-coupling — отдельный долг, ортогонален |
| 2026-06-10 | Поля/действия | В `ecs-logging-conventions.md` добавлены: «Анатомия лог-строки», полная карта call-site→event.action→outcome (92 call-sites), дополнен `error.*` (ручные `error`/`error_type`/`diag_code` + `error.code`). Карта = источник `EventAction` enum (Фаза 2) |
| 2026-06-14 | Старт реализации | Рабочий порядок: сначала границы модулей и guard-тесты, затем `ecs_transform`, taxonomy validation, один вертикальный срез зоны. ADR остаётся только для окончательно принятых решений |
| 2026-06-14 | `ecs-logging` | Не используем как production formatter; новых runtime-зависимостей на текущий этап не добавляем |
| 2026-06-14 | Контракт событий | ACCEPTED: `ObservabilityEvent` — frozen dataclass intention-object; generic `ObservabilityEventSink` — внутренний transport; наружу для usecases выдаются узкие zone-specific Protocols/adapters. Первый vertical slice — runtime/pipeline lifecycle через `PipelineHooks` |
| 2026-06-15 | Phase 1 guard-механизм | Для observability-specific правил выбран AST ratchet guard вместо новых import-linter contracts: он точнее покрывает reserved roots, ownership `ecs_transform`, taxonomy aliases и known legacy usecase imports. Import-linter остаётся для общих layer contracts |
| 2026-06-15 | `run-completed` vs `run-failed` | `run-completed` + `event.outcome=failure` означает graceful non-zero diagnostic exit; `run-failed` зарезервирован для unhandled command-level exception и подключается позже при миграции legacy exception path |
| 2026-06-15 | Темы 4/5/7 | Закрыты в Phase 1: `error.*` precedence (ADR + `_merge_error_fields` + тест); `log.logger` через `add_logger_name` (гранулярность по компоненту); foreign-логи через `foreign_pre_chain`+`ecs_transform` (robustness-тест) |
| 2026-06-15 | Phase 1 отгружен | Каркас ECS (renderer + контракт + sink/adapters + lifecycle slice + guard-тесты) принят; план заморожен в `archive/phase-1-plan.md` |
| 2026-06-15 | Реструктуризация worknote | Вариант 1: Phase 1 → `archive/`, открытая работа → `phase-2-design.md`, принятый дизайн → ADR (без дублирования); worknote оставлен как журнал + навигация |
| 2026-06-15 | Модель `sensitive` | Зафиксировано: `sensitive` — handling-policy метаданные поля (ортогонально `tier`), вход для validator/registry/renderer/redaction/ES-mapping, а не «ключи для redaction». Поверхности S1–S5 (см. `phase-2-design.md`): S1 contract-test + S2 registry экспонирует набор — в Phase 2; S3 renderer value-agnostic; S4 redaction-extension открыт; S5 ES-mapping — follow-up. Первичный контроль — call-site discipline + contract-test |
| 2026-06-15 | Registry lifecycle & failure model | Принято (форки A/C): реестр собирается eager на bootstrap (`build_structured_logging_runtime`), immutable, инъекция в `ecs_transform` замыканием (устраняет гонку потоков и file-I/O на hot-path); fail-safe деградация до labels-only + one-shot WARNING в проде, fail-fast при `diagnostics.strict`; одна полная валидация на процесс. Добавляет: параметр `strict_taxonomy`, action `taxonomy-load-degraded`, флаг `taxonomy_degraded`. Детали — `phase-2-design.md` §Registry lifecycle |
| 2026-06-15 | Resolution spec `ecs_transform` (п.7) | Зафиксирован порядок резолва (meta/control → alias → canonical passthrough → labels catch-all) + таблица коллизий. D7.1: добавить contract-тесты alias∩meta=∅ и alias∩roots=∅. **D7.2=(a)**: объявить алиасы `schema_version→labels.schema_version`, `git_rev→labels.git_rev` (2 field-entry). D7.3 unknown dotted→labels (strict dev-warn опц.); D7.4 коллизии last-wins; D7.5 canonical passthrough / labels coerce |
| 2026-06-15 | Golden / behavior-preservation (п.4) | Принято: exact-dict golden-тест `make_ecs_transform(registry)` на 8 группах кейсов (7 представительных + degraded-mode); goldens снимаются на Phase-1-выводе → доказывают неизменность вывода после замены загрузчика (C). Golden = исполняемая форма правил п.7; консолидирует ad-hoc проверки из `test_ecs_transform.py` |
| 2026-06-15 | Fork B — registry-backed defaults | Принято B1 в Phase 2: `level`/`kind` резолвятся в sink из реестра (precedence явный override → registry → fallback), адаптеры перестают хардкодить; `outcome` остаётся рантайм-фактом адаптера (policy `actions.yaml` → валидация golden-тестом п.4, не дефолт-значение); null-safe lookup (runtime lenient); реестр инъектируется в sink через DI. Behavior-preserving (hardcode == YAML). Детали — `phase-2-design.md` §Fork B |
| 2026-06-15 | D/F + тест-инфра + риск-реестр | D.1 membership через AST-скан адаптеров (`action` ∈ `actions.yaml`), runtime lenient; F мягкий sync `callsite-map` ⊆ `actions.yaml`. п.10: вендоренный ECS-срез `ecs_fields_8_11.json` (`owner=ecs` ⊆ срез) + autouse root-logger snapshot. п.11: сведён сводный риск-реестр Phase 2. **Дизайн Phase 2 закрыт.** Детали — `phase-2-design.md` |
| 2026-06-15 | Phase 2 design — уточнения + ADR | (1) ADR↔design синхронны по `sensitive` (Phase 2 = validate+expose; raw/safe runtime enforcement вне фазы); (2) registry — конкретная infra-модель `taxonomy.py`, **без Protocol в `common`** (оба потребителя infra); (3) `make_ecs_transform(registry)` — основной API, прото-функции `field_aliases()`/`canonical_field_keys()` → только compat/test поверх default registry; (4) degraded — свойство `StructuredLoggingRuntime.taxonomy_degraded_reason`, return type build не меняем. Golden — напрямую через `make_ecs_transform(real_registry)`, не через runtime. Дизайн Phase 2 кратко перенесён в ADR §Phase 2 |

---

## Связанные документы

- [README.md](./README.md) — индекс папки заметок
- [phase-2-design.md](./phase-2-design.md) — проектирование Phase 2 (открытые решения)
- [archive/phase-1-plan.md](./archive/phase-1-plan.md) — замороженный план Phase 1
- [OBSERVABILITY-DEC-003](../../adr/observability/OBSERVABILITY-DEC-003-ecs-renderer-and-field-mapping.md) — решение
- [OBSERVABILITY-PROBLEM-003](../../adr/observability/OBSERVABILITY-PROBLEM-003-non-ecs-log-shape.md) — проблема
- [ecs-logging-conventions.md](../../dev/layers/observability/ecs-logging-conventions.md) — семантика полей/уровней/действий
- [observability-logging.md](../../dev/layers/observability/observability-logging.md) — runtime/процессоры/redaction
- `connector/infra/logging/runtime.py`, `connector/infra/logging/ecs.py`
