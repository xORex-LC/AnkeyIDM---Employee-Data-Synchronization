"""Golden-тесты ECS processor для сохранения Phase 1 JSON-контракта."""

from __future__ import annotations

import pytest

from connector.infra.logging.ecs import make_ecs_transform
from connector.infra.logging.taxonomy import (
    empty_observability_taxonomy,
    load_observability_taxonomy,
)

pytestmark = pytest.mark.unit


class _Logger:
    name = "tests.fallback"


_ecs_transform = make_ecs_transform(load_observability_taxonomy())


def test_ecs_transform_golden_run_started_full_runtime_meta() -> None:
    payload = _ecs_transform(
        _Logger(),
        "info",
        {
            "timestamp": "2026-06-15T00:00:00Z",
            "event": "Command started",
            "level": "info",
            "logger": "nexus.planner.lifecycle",
            "action": "run-started",
            "run_id": "run-1",
            "pipeline_run_id": "pipe-1",
            "component": "planner",
            "dataset": "employees",
            "schema_version": "1.0",
            "host": "node-a",
            "pid": 1234,
            "app_version": "2.0.0",
            "git_rev": "abc123",
        },
    )

    assert payload == {
        "@timestamp": "2026-06-15T00:00:00Z",
        "ecs.version": "8.11",
        "event.action": "run-started",
        "event.dataset": "employees",
        "host.name": "node-a",
        "labels.git_rev": "abc123",
        "labels.pipeline_run_id": "pipe-1",
        "labels.schema_version": "1.0",
        "log.level": "info",
        "log.logger": "nexus.planner.lifecycle",
        "message": "Command started",
        "process.pid": 1234,
        "service.name": "nexus-etl",
        "service.type": "planner",
        "service.version": "2.0.0",
        "trace.id": "run-1",
    }


def test_ecs_transform_golden_stage_completed_metric() -> None:
    payload = _ecs_transform(
        _Logger(),
        "info",
        {
            "event": "Stage completed",
            "level": "info",
            "logger": "nexus.pipeline",
            "action": "stage-completed",
            "dataset": "employees",
            "stage_name": "match",
            "items_count": 12,
            "duration_ns": 456,
            "outcome": "success",
            "kind": "metric",
        },
    )

    assert payload == {
        "ecs.version": "8.11",
        "event.action": "stage-completed",
        "event.dataset": "employees",
        "event.duration": 456,
        "event.kind": "metric",
        "event.outcome": "success",
        "log.level": "info",
        "log.logger": "nexus.pipeline",
        "message": "Stage completed",
        "nexus.stage.items_count": 12,
        "nexus.stage.name": "match",
        "service.name": "nexus-etl",
    }


def test_ecs_transform_golden_warning_degraded_event() -> None:
    payload = _ecs_transform(
        _Logger(),
        "warning",
        {
            "event": "Taxonomy load degraded",
            "level": "warning",
            "logger": "nexus.observability",
            "action": "taxonomy-load-degraded",
            "outcome": "failure",
            "kind": "event",
            "reason": "invalid taxonomy",
        },
    )

    assert payload == {
        "ecs.version": "8.11",
        "event.action": "taxonomy-load-degraded",
        "event.kind": "event",
        "event.outcome": "failure",
        "labels.reason": "invalid taxonomy",
        "log.level": "warning",
        "log.logger": "nexus.observability",
        "message": "Taxonomy load degraded",
        "service.name": "nexus-etl",
    }


def test_ecs_transform_golden_error_exception_and_manual_code_precedence() -> None:
    payload = _ecs_transform(
        _Logger(),
        "error",
        {
            "event": "Stage failed",
            "level": "error",
            "logger": "nexus.pipeline",
            "action": "stage-failed",
            "error_code": "STAGE_FAILED",
            "exception": [
                {
                    "type": "ValueError",
                    "value": "bad input",
                    "stack": ["traceback"],
                }
            ],
        },
    )

    assert payload == {
        "ecs.version": "8.11",
        "error.code": "STAGE_FAILED",
        "error.message": "bad input",
        "error.stack_trace": (
            '[{"stack": ["traceback"], "type": "ValueError", "value": "bad input"}]'
        ),
        "error.type": "ValueError",
        "event.action": "stage-failed",
        "log.level": "error",
        "log.logger": "nexus.pipeline",
        "message": "Stage failed",
        "service.name": "nexus-etl",
    }


def test_ecs_transform_golden_foreign_log_minimal_input() -> None:
    payload = _ecs_transform(
        _Logger(),
        "error",
        {
            "event": "Foreign error",
            "level": "error",
        },
    )

    assert payload == {
        "ecs.version": "8.11",
        "log.level": "error",
        "log.logger": "tests.fallback",
        "message": "Foreign error",
        "service.name": "nexus-etl",
    }


def test_ecs_transform_golden_unknown_business_and_dotted_fields() -> None:
    payload = _ecs_transform(
        _Logger(),
        "info",
        {
            "event": "Unknown fields",
            "business_value": "abc",
            "event.datset": "typo",
            "nested": {"b": 2, "a": 1},
        },
    )

    assert payload == {
        "ecs.version": "8.11",
        "labels.business_value": "abc",
        "labels.event_datset": "typo",
        "labels.nested": '{"a": 1, "b": 2}',
        "log.level": "info",
        "log.logger": "tests.fallback",
        "message": "Unknown fields",
        "service.name": "nexus-etl",
    }


def test_ecs_transform_golden_structural_root_kwargs_become_labels() -> None:
    payload = _ecs_transform(
        _Logger(),
        "info",
        {
            "event": "Structural kwarg",
            "trace": "trace-as-value",
            "labels": {"source": "bad"},
            "nexus": {"stage": "bad"},
            "tags": ["one", "two"],
        },
    )

    assert payload == {
        "ecs.version": "8.11",
        "labels.labels": '{"source": "bad"}',
        "labels.nexus": '{"stage": "bad"}',
        "labels.tags": ["one", "two"],
        "labels.trace": "trace-as-value",
        "log.level": "info",
        "log.logger": "tests.fallback",
        "message": "Structural kwarg",
        "service.name": "nexus-etl",
    }


def test_ecs_transform_golden_degraded_registry_uses_labels_only() -> None:
    transform = make_ecs_transform(
        empty_observability_taxonomy(reason="taxonomy load failed")
    )

    payload = transform(
        _Logger(),
        "warning",
        {
            "event": "Taxonomy load degraded",
            "level": "warning",
            "logger": "nexus.observability",
            "action": "taxonomy-load-degraded",
            "dataset": "employees",
            "component": "observability",
            "schema_version": "1.0",
        },
    )

    assert payload == {
        "ecs.version": "8.11",
        "labels.action": "taxonomy-load-degraded",
        "labels.component": "observability",
        "labels.dataset": "employees",
        "labels.schema_version": "1.0",
        "log.level": "warning",
        "log.logger": "nexus.observability",
        "message": "Taxonomy load degraded",
        "service.name": "nexus-etl",
    }
