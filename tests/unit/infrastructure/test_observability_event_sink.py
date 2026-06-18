"""Юнит-тесты bridge между ObservabilityEvent и structlog logger."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from connector.common.observability import (
    EventKind,
    EventOutcome,
    LogLevel,
    ObservabilityError,
    ObservabilityEvent,
)
from connector.infra.logging.event_sink import StructlogObservabilityEventSink
from connector.infra.logging.lifecycle import RuntimeLifecycleEventAdapter
from connector.infra.logging.taxonomy import (
    empty_observability_taxonomy,
    load_observability_taxonomy,
)

pytestmark = pytest.mark.unit

_REGISTRY = load_observability_taxonomy()


@dataclass
class _Logger:
    calls: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)

    def info(self, message: str, **kwargs: Any) -> None:
        self.calls.append(("info", message, kwargs))

    def error(self, message: str, **kwargs: Any) -> None:
        self.calls.append(("error", message, kwargs))

    def debug(self, message: str, **kwargs: Any) -> None:
        self.calls.append(("debug", message, kwargs))

    def warning(self, message: str, **kwargs: Any) -> None:
        self.calls.append(("warning", message, kwargs))

    def critical(self, message: str, **kwargs: Any) -> None:
        self.calls.append(("critical", message, kwargs))


def test_event_sink_emits_event_contract_as_structlog_kwargs() -> None:
    logger = _Logger()
    sink = StructlogObservabilityEventSink(logger=logger, registry=_REGISTRY)

    sink.emit(
        ObservabilityEvent(
            action="stage-completed",
            message="Pipeline stage completed",
            fields={"stage_name": "match", "items_count": 3},
            level=LogLevel.INFO,
            outcome=EventOutcome.SUCCESS,
            kind=EventKind.METRIC,
            duration_ns=42,
        )
    )

    assert logger.calls == [
        (
            "info",
            "Pipeline stage completed",
            {
                "action": "stage-completed",
                "stage_name": "match",
                "items_count": 3,
                "outcome": "success",
                "kind": "metric",
                "duration_ns": 42,
            },
        )
    ]


def test_event_sink_adds_manual_error_fields_and_exception_object() -> None:
    logger = _Logger()
    sink = StructlogObservabilityEventSink(logger=logger, registry=_REGISTRY)
    exc = RuntimeError("boom")

    sink.emit(
        ObservabilityEvent(
            action="stage-failed",
            message="Pipeline stage failed",
            level=LogLevel.ERROR,
            error=ObservabilityError(
                type="RuntimeError",
                message="boom",
                code="STAGE_FAILED",
            ),
        ),
        exc_info=exc,
    )

    assert logger.calls == [
        (
            "error",
            "Pipeline stage failed",
            {
                "action": "stage-failed",
                "error_type": "RuntimeError",
                "error_message": "boom",
                "error_code": "STAGE_FAILED",
                "kind": "event",
                "exc_info": exc,
            },
        )
    ]


def test_event_sink_rejects_dotted_event_fields() -> None:
    logger = _Logger()
    sink = StructlogObservabilityEventSink(logger=logger, registry=_REGISTRY)

    with pytest.raises(ValueError):
        sink.emit(
            ObservabilityEvent(
                action="bad-event",
                message="Bad event",
                fields={"event.action": "bad-event"},
            )
        )


def test_runtime_lifecycle_taxonomy_degraded_warning_is_explicit() -> None:
    logger = _Logger()
    adapter = RuntimeLifecycleEventAdapter(
        sink=StructlogObservabilityEventSink(logger=logger, registry=_REGISTRY)
    )

    adapter.taxonomy_load_degraded(reason="broken\n taxonomy")

    assert logger.calls == [
        (
            "warning",
            "Observability taxonomy load degraded",
            {
                "action": "taxonomy-load-degraded",
                "scope": "observability",
                "reason": "broken taxonomy",
                "outcome": "failure",
                "kind": "event",
            },
        )
    ]


def test_event_sink_uses_registry_defaults_when_event_omits_level_and_kind() -> None:
    logger = _Logger()
    sink = StructlogObservabilityEventSink(logger=logger, registry=_REGISTRY)

    sink.emit(
        ObservabilityEvent(
            action="stage-completed",
            message="Pipeline stage completed",
            fields={"stage_name": "match"},
        )
    )

    assert logger.calls == [
        (
            "info",
            "Pipeline stage completed",
            {
                "action": "stage-completed",
                "stage_name": "match",
                "kind": "metric",
            },
        )
    ]


def test_event_sink_explicit_level_and_kind_win_over_registry_defaults() -> None:
    logger = _Logger()
    sink = StructlogObservabilityEventSink(logger=logger, registry=_REGISTRY)

    sink.emit(
        ObservabilityEvent(
            action="stage-completed",
            message="Pipeline stage completed",
            level=LogLevel.WARNING,
            kind=EventKind.EVENT,
        )
    )

    assert logger.calls == [
        (
            "warning",
            "Pipeline stage completed",
            {
                "action": "stage-completed",
                "kind": "event",
            },
        )
    ]


def test_event_sink_unknown_action_falls_back_to_info_event_kind() -> None:
    logger = _Logger()
    sink = StructlogObservabilityEventSink(
        logger=logger, registry=empty_observability_taxonomy(reason="empty")
    )

    sink.emit(ObservabilityEvent(action="unknown-action", message="Unknown action"))

    assert logger.calls == [
        (
            "info",
            "Unknown action",
            {
                "action": "unknown-action",
                "kind": "event",
            },
        )
    ]


def test_event_sink_does_not_inject_outcome_when_event_omits_it() -> None:
    logger = _Logger()
    sink = StructlogObservabilityEventSink(logger=logger, registry=_REGISTRY)

    sink.emit(ObservabilityEvent(action="run-completed", message="Run completed"))

    _, _, fields = logger.calls[0]
    assert fields["kind"] == "event"
    assert "outcome" not in fields
