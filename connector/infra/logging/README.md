# connector/infra/logging

## Назначение

Логирующая инфраструктура observability-модели: `structlog`, stderr JSON и daily+size file sink.

## Файлы

| Файл | Назначение |
|---|---|
| `runtime.py` | `StructuredLoggingRuntime`, `DailySizeRotatingFileHandler`, `bind_observability_context()` — structlog runtime с stderr/file sinks, human console text renderer и stdlib bridge для foreign-логов |
| `ecs.py` | `make_ecs_transform(registry)` и compatibility `ecs_transform` — финальный JSON processor, который переводит короткие observability aliases в ECS/project dotted keys и отправляет неизвестные бизнес-поля в `labels.*` |
| `taxonomy.py` | Pydantic loader/registry для machine-readable ECS logging taxonomy (`actions.yaml`, `fields/*.yaml`) |
| `event_sink.py` | `StructlogObservabilityEventSink` — bridge `ObservabilityEvent` → native structlog logger; default `level`/`kind` берёт из taxonomy registry без знания о финальном ECS JSON |
| `lifecycle.py` | `RuntimeLifecycleEventAdapter`, `PipelineLifecycleEventAdapter` — семантические adapters для command/run и pipeline stage lifecycle |
| `redaction.py` | `LogRedactionEngine` — единый redaction engine для structlog event_dict, foreign-логов, traceback и stream-capture |
| `topology.py` | `StructlogTopologyEventSink` — bridge `TopologyEventSink` → native structlog logger (`scope=topology`) |

## Runtime-модель

- CLI orchestration пишет JSON в `stderr` и активный лог в `var/logs/<component>/<YYYY-MM-DD>_<component>.log`.
- Повторные запуски в тот же день дописывают в тот же файл; size-roll создаёт backup-файлы в том же component partition.
- CLI call-sites пишут через native structlog `logger.info/warning/error(event, scope=..., **fields)`.
- Новые lifecycle-события Phase 1 идут через `ObservabilityEvent` и узкие lifecycle adapters; call-site не формирует dotted ECS keys вручную.
- Lifecycle adapters эмитят semantic events: `level`/`kind` по умолчанию резолвит
  `StructlogObservabilityEventSink` через taxonomy registry. Исключение — `taxonomy-load-degraded`,
  где `WARNING` задаётся явно, потому что degraded registry пустой.
- JSON sinks проходят через единый processor из `make_ecs_transform(registry)` после exception normalization, redaction и cleanup processor meta; text/human sinks ECS-transform не используют.
- Phase 2 вводит валидированный taxonomy registry: YAML читается на bootstrap/в тестах, а не как
  произвольная логика call-site-ов. Bare `ecs_transform` оставлен только как compatibility/test
  surface поверх default registry; runtime его напрямую не использует.
- Если registry не загружается, `strict_taxonomy=true` прерывает bootstrap понятным
  `TaxonomyLoadError` до настройки handlers. В non-strict режиме runtime использует empty
  degraded registry, сохраняет `taxonomy_degraded_reason` и orchestration эмитит один
  `taxonomy-load-degraded` WARNING после успешной инициализации logging runtime.
- Во время интерактивных prompt-секций console mirror временно suppress-ится через `InteractiveIoGate`, но файловый sink продолжает писать события.
- `console.format=text` рендерится как операторский однострочный формат вида `[INFO] vault core: Command started | run_id=... | ...`.
- `file.format=text` остаётся плоским `key=value`-форматом, но поля разделяются через ` | ` для лучшей читаемости.

## Зависимости

**Зависит от:** `structlog`, stdlib `logging`, `connector.common.observability`.
**Используется:** `delivery/cli/runtime/orchestrator.py`, `delivery/cli/stream_capture.py`, topology/report/runtime tests.
