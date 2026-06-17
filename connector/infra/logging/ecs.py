"""ECS transform — финальный processor JSON-формы для структурных логов.

Модуль владеет преобразованием внутренних structlog event dictionaries в JSON-поля,
совместимые с Elastic Common Schema. Это единственное runtime-место, где короткие
observability aliases превращаются в dotted ECS или project-specific keys.

Границы ответственности:
    - Нормализовать structlog event dictionaries в ECS-совместимые JSON dictionaries.
    - Резолвить короткие field aliases через machine-readable taxonomy.
    - Удерживать неизвестные бизнес-поля под `labels.*`.

Вне ответственности:
    - Redaction секретов перед rendering.
    - Выбор момента, когда бизнес-компонент должен эмитить log event.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Mapping

from .taxonomy import (
    ObservabilityTaxonomyRegistry,
    load_observability_taxonomy,
)

ECS_VERSION = "8.11"
SERVICE_NAME = "nexus-etl"

STRUCTURAL_ROOTS = frozenset(
    {
        "@timestamp",
        "component",
        "ecs",
        "error",
        "event",
        "exception",
        "file",
        "host",
        "http",
        "labels",
        "log",
        "message",
        "nexus",
        "process",
        "service",
        "span",
        "tags",
        "trace",
        "url",
    }
)

_LABEL_KEY_RE = re.compile(r"[^A-Za-z0-9_]+")
EcsTransform = Callable[[Any, str, dict[str, Any]], dict[str, Any]]
_DEFAULT_TAXONOMY_REGISTRY: ObservabilityTaxonomyRegistry | None = None


def ecs_transform(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Отрендерить событие через registry по умолчанию.

    Runtime-контур должен использовать `make_ecs_transform(registry)`, чтобы registry
    загружался на bootstrap и не читался из processor hot-path. Эта функция остаётся
    совместимым API для unit-тестов и переходного кода.
    """
    return make_ecs_transform(_default_taxonomy_registry())(
        _logger, _method_name, event_dict
    )


def make_ecs_transform(registry: ObservabilityTaxonomyRegistry) -> EcsTransform:
    """Создать ECS processor, привязанный к валидированному taxonomy registry."""
    aliases = dict(registry.field_aliases)
    known_keys = frozenset(registry.canonical_field_keys)

    def ecs_transform(
        _logger: Any, _method_name: str, event_dict: dict[str, Any]
    ) -> dict[str, Any]:
        return _render_ecs_event(
            aliases=aliases,
            known_keys=known_keys,
            logger=_logger,
            event_dict=event_dict,
        )

    return ecs_transform


def _render_ecs_event(
    *,
    aliases: Mapping[str, str],
    known_keys: frozenset[str],
    logger: Any,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    rendered: dict[str, Any] = {
        "ecs.version": ECS_VERSION,
        "service.name": SERVICE_NAME,
    }
    pending_error: dict[str, Any] = {}

    for raw_key, value in event_dict.items():
        if value is None:
            continue
        if raw_key == "timestamp":
            rendered["@timestamp"] = value
            continue
        if raw_key == "event":
            rendered["message"] = value
            continue
        if raw_key == "level":
            rendered["log.level"] = str(value).lower()
            continue
        if raw_key == "logger":
            rendered["log.logger"] = value
            continue
        if raw_key == "exception":
            pending_error.update(_exception_error_fields(value))
            continue

        canonical_key = aliases.get(raw_key)
        if canonical_key is not None:
            rendered[canonical_key] = value
            continue

        if raw_key in known_keys:
            rendered[raw_key] = value
            continue

        if raw_key in {"exc_info", "stack_info"}:
            continue

        _put_label(rendered, raw_key, value)

    _merge_error_fields(rendered, pending_error)
    rendered.setdefault("message", "")
    rendered.setdefault("log.level", "info")
    rendered.setdefault("log.logger", _logger_name(logger))
    return rendered


def field_aliases() -> dict[str, str]:
    """Вернуть aliases из registry по умолчанию для совместимости старых тестов."""
    return dict(_default_taxonomy_registry().field_aliases)


def canonical_field_keys() -> frozenset[str]:
    """Вернуть canonical field keys из registry по умолчанию."""
    return _default_taxonomy_registry().canonical_field_keys


def validate_field_name_for_event_contract(key: str) -> None:
    """Отклонить ECS structural roots и dotted keys в `ObservabilityEvent.fields`."""
    if "." in key:
        raise ValueError(
            f"ObservabilityEvent field keys must be aliases, not dotted keys: {key}"
        )
    if key in STRUCTURAL_ROOTS:
        raise ValueError(
            f"ObservabilityEvent field key uses reserved structural root: {key}"
        )


def _default_taxonomy_registry() -> ObservabilityTaxonomyRegistry:
    global _DEFAULT_TAXONOMY_REGISTRY
    if _DEFAULT_TAXONOMY_REGISTRY is None:
        _DEFAULT_TAXONOMY_REGISTRY = load_observability_taxonomy()
    return _DEFAULT_TAXONOMY_REGISTRY


def _merge_error_fields(
    rendered: dict[str, Any], exception_fields: Mapping[str, Any]
) -> None:
    manual_code = rendered.get("error.code")
    for key, value in exception_fields.items():
        if value is not None:
            rendered[key] = value
    if manual_code is not None:
        rendered["error.code"] = manual_code


def _exception_error_fields(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return {"error.stack_trace": value}
    if isinstance(value, Mapping):
        return _exception_mapping_fields(value)
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, Mapping):
            fields = _exception_mapping_fields(first)
            stack_trace = _stack_trace_from_exception_list(value)
            if stack_trace:
                fields["error.stack_trace"] = stack_trace
            return fields
    return {"error.stack_trace": _coerce_label_value(value)}


def _exception_mapping_fields(value: Mapping[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    exc_type = value.get("type") or value.get("exc_type")
    exc_message = value.get("value") or value.get("message") or value.get("exc_value")
    if exc_type is not None:
        fields["error.type"] = str(exc_type)
    if exc_message is not None:
        fields["error.message"] = str(exc_message)
    stack_trace = value.get("stack") or value.get("traceback")
    if stack_trace is not None:
        fields["error.stack_trace"] = _coerce_label_value(stack_trace)
    return fields


def _stack_trace_from_exception_list(value: list[Any]) -> str | None:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def _put_label(rendered: dict[str, Any], key: str, value: Any) -> None:
    label_key = f"labels.{_label_suffix(key)}"
    rendered[label_key] = _coerce_label_value(value)


def _label_suffix(key: str) -> str:
    normalized = _LABEL_KEY_RE.sub("_", key.strip().replace(".", "_")).strip("_")
    return normalized or "field"


def _coerce_label_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, list) and all(
        isinstance(item, (str, int, float, bool)) or item is None for item in value
    ):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(value)


def _logger_name(logger: Any) -> str:
    name = getattr(logger, "name", None)
    if isinstance(name, str) and name:
        return name
    return "unknown"


__all__ = [
    "ECS_VERSION",
    "STRUCTURAL_ROOTS",
    "canonical_field_keys",
    "ecs_transform",
    "field_aliases",
    "make_ecs_transform",
    "validate_field_name_for_event_contract",
]
