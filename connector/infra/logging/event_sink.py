"""Observability event sink — мост от event-контрактов к structlog.

Модуль адаптирует нейтральные к runtime значения `ObservabilityEvent` к активному
structlog-логгеру команды. Он не рендерит ECS JSON, а только эмитит structured kwargs,
которые logging runtime позже нормализует через `ecs_transform`.

Границы ответственности:
    - Валидировать ключи event fields до попадания в logging backend.
    - Диспетчеризовать events на запрошенный log level.
    - Сохранять manual error metadata и позволять live exceptions нести stack traces.

Вне ответственности:
    - Управление handler lifecycle или сборка logger.
    - Mapping aliases в финальные ECS field names.
"""

from __future__ import annotations

from typing import Any

from connector.common.observability.events import (
    EventKind,
    LogLevel,
    ObservabilityError,
    ObservabilityEvent,
)
from connector.common.observability.ports import ObservabilityEventSink
from connector.infra.logging.ecs import validate_field_name_for_event_contract
from connector.infra.logging.taxonomy import ObservabilityTaxonomyRegistry


class StructlogObservabilityEventSink(ObservabilityEventSink):
    """Эмитить observability event intentions в текущий structlog logger."""

    def __init__(
        self, *, logger: Any, registry: ObservabilityTaxonomyRegistry
    ) -> None:
        self._logger = logger
        self._registry = registry

    def emit(self, event: ObservabilityEvent, *, exc_info: object = None) -> None:
        level = _resolve_level(event, self._registry)
        kind = _resolve_kind(event, self._registry)
        fields = _event_to_fields(event, kind=kind)
        _dispatch_log(
            self._logger,
            level,
            event.message,
            fields,
            exc_info=exc_info,
        )


def _event_to_fields(event: ObservabilityEvent, *, kind: EventKind) -> dict[str, Any]:
    fields: dict[str, Any] = {"action": event.action}
    for key, value in event.fields.items():
        validate_field_name_for_event_contract(key)
        fields[key] = value
    if event.outcome is not None:
        fields["outcome"] = event.outcome.value
    fields["kind"] = kind.value
    if event.duration_ns is not None:
        fields["duration_ns"] = event.duration_ns
    if event.error is not None:
        fields.update(_error_fields(event.error))
    return fields


def _resolve_level(
    event: ObservabilityEvent, registry: ObservabilityTaxonomyRegistry
) -> LogLevel:
    return event.level or registry.default_level_for(event.action) or LogLevel.INFO


def _resolve_kind(
    event: ObservabilityEvent, registry: ObservabilityTaxonomyRegistry
) -> EventKind:
    return event.kind or registry.kind_for(event.action) or EventKind.EVENT


def _error_fields(error: ObservabilityError) -> dict[str, str]:
    fields = {
        "error_type": error.type,
        "error_message": error.message,
    }
    if error.code is not None:
        fields["error_code"] = error.code
    return fields


def _dispatch_log(
    logger: Any,
    level: LogLevel,
    message: str,
    fields: dict[str, Any],
    *,
    exc_info: object,
) -> None:
    kwargs = dict(fields)
    if exc_info is not None:
        kwargs["exc_info"] = exc_info
    if level == LogLevel.CRITICAL:
        logger.critical(message, **kwargs)
    elif level == LogLevel.ERROR:
        logger.error(message, **kwargs)
    elif level == LogLevel.WARNING:
        logger.warning(message, **kwargs)
    elif level == LogLevel.DEBUG:
        logger.debug(message, **kwargs)
    else:
        logger.info(message, **kwargs)


__all__ = ["StructlogObservabilityEventSink"]
