"""Юнит-тесты loader-а observability logging taxonomy."""

from __future__ import annotations

from pathlib import Path

import pytest

from connector.common.observability.events import EventKind, LogLevel
from connector.infra.logging.taxonomy import (
    TaxonomyLoadError,
    empty_observability_taxonomy,
    load_observability_taxonomy,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
TAXONOMY_ROOT = REPO_ROOT / "connector" / "common" / "observability" / "taxonomy"


def test_load_observability_taxonomy_builds_runtime_registry() -> None:
    registry = load_observability_taxonomy(TAXONOMY_ROOT)

    assert len(registry.action_names) == 183
    assert len(registry.canonical_field_keys) == 410
    assert registry.ecs_version == "8.11"
    assert registry.field_aliases["component"] == "service.type"
    assert registry.field_aliases["schema_version"] == "labels.schema_version"
    assert registry.field_aliases["git_rev"] == "labels.git_rev"
    assert registry.action("stage-completed") is not None
    assert registry.default_level_for("stage-completed") == LogLevel.INFO
    assert registry.kind_for("stage-completed") == EventKind.METRIC


def test_load_observability_taxonomy_exposes_sensitive_metadata() -> None:
    registry = load_observability_taxonomy(TAXONOMY_ROOT)

    assert "nexus.record.identity.value_fingerprint" in registry.sensitive_keys
    assert isinstance(registry.sensitive_aliases, frozenset)
    assert registry.sensitive_aliases <= frozenset(registry.field_aliases)
    assert "component" not in registry.sensitive_aliases


def test_load_observability_taxonomy_maps_trace_level_to_debug_runtime_level() -> None:
    registry = load_observability_taxonomy(TAXONOMY_ROOT)

    assert registry.action("cache-page-fetched") is not None
    assert registry.default_level_for("cache-page-fetched") == LogLevel.DEBUG


def test_empty_observability_taxonomy_returns_degraded_registry() -> None:
    registry = empty_observability_taxonomy(reason="invalid yaml")

    assert registry.degraded_reason == "invalid yaml"
    assert registry.action("stage-completed") is None
    assert registry.default_level_for("stage-completed") is None
    assert registry.kind_for("stage-completed") is None
    assert registry.field_aliases == {}
    assert registry.canonical_field_keys == frozenset()
    assert registry.sensitive_keys == frozenset()
    assert registry.sensitive_aliases == frozenset()


def test_load_observability_taxonomy_raises_actionable_error_for_invalid_yaml(
    tmp_path: Path,
) -> None:
    taxonomy_root = tmp_path / "taxonomy"
    fields_root = taxonomy_root / "fields"
    fields_root.mkdir(parents=True)
    (taxonomy_root / "actions.yaml").write_text(
        """
schema_version: 1
ecs_version: "8.11"
actions:
- name: stage-started
  zone: 03-pipeline-stage-lifecycle
  bucket: milestone
  default_level: info
  outcome: none
  kind: event
  status: planned
  required_fields: []
""",
        encoding="utf-8",
    )
    (fields_root / "00-base.yaml").write_text(
        """
schema_version: 1
ecs_version: "8.11"
fields:
- key: event.action
  aliases: [action]
  ecs_type: keyword
  owner: ecs
  tier: core
  description: missing sensitive flag
""",
        encoding="utf-8",
    )

    with pytest.raises(TaxonomyLoadError, match="Failed to load observability taxonomy"):
        load_observability_taxonomy(taxonomy_root)
