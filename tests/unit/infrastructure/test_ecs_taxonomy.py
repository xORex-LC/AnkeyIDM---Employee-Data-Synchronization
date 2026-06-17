"""Контракт-тесты machine-readable ECS logging taxonomy."""

from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from connector.infra.logging.ecs import ECS_VERSION, STRUCTURAL_ROOTS
from connector.infra.logging.taxonomy import load_observability_taxonomy

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
TAXONOMY_ROOT = REPO_ROOT / "connector" / "common" / "observability" / "taxonomy"
FIELDS_ROOT = TAXONOMY_ROOT / "fields"
ECS_FIELDS_SLICE = Path(__file__).with_name("ecs_fields_8_11.json")
ZONES_ROOT = REPO_ROOT / "docs" / "dev" / "layers" / "observability" / "ecs-logging-taxonomy" / "zones"

ACTION_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
META_CONTROL_KEYS = frozenset(
    {"timestamp", "event", "level", "logger", "exception", "exc_info", "stack_info", "message"}
)
ROOT_FIELD_KEYS = frozenset({"@timestamp", "message"})
APPROVED_STRUCTURAL_ALIASES = frozenset(
    {
        "component",  # runtime context input -> service.type
        "host",  # runtime context input -> host.name
        "error",  # legacy safe error message alias; remove when call-sites migrate to error_message
    }
)


def _actions_payload() -> dict[str, Any]:
    return yaml.safe_load((TAXONOMY_ROOT / "actions.yaml").read_text(encoding="utf-8"))


def _field_payloads() -> list[tuple[Path, dict[str, Any]]]:
    return [
        (path, yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        for path in sorted(FIELDS_ROOT.glob("*.yaml"))
    ]


def _field_entries() -> list[tuple[Path, dict[str, Any]]]:
    entries: list[tuple[Path, dict[str, Any]]] = []
    for path, payload in _field_payloads():
        entries.extend((path, entry) for entry in payload.get("fields") or ())
    return entries


def test_action_names_are_unique_kebab_case_values() -> None:
    actions = _actions_payload()["actions"]
    names = [str(action["name"]) for action in actions]

    assert len(names) == len(set(names))
    assert [name for name in names if not ACTION_NAME_RE.fullmatch(name)] == []


def test_field_keys_are_unique_dotted_paths() -> None:
    keys = [str(entry["key"]) for _, entry in _field_entries()]
    invalid = [key for key in keys if key not in ROOT_FIELD_KEYS and "." not in key]

    assert len(keys) == len(set(keys))
    assert invalid == []


def test_action_required_fields_exist_in_field_registry() -> None:
    registry = load_observability_taxonomy(TAXONOMY_ROOT)
    missing: list[str] = []
    for action in registry.actions.values():
        for field_key in action.required_fields:
            if field_key not in registry.canonical_field_keys:
                missing.append(f"{action.name}: {field_key}")

    assert missing == []


def test_field_roots_are_allowed_structural_roots() -> None:
    violations: list[str] = []
    for path, entry in _field_entries():
        key = str(entry["key"])
        root = key if key == "@timestamp" else key.split(".", 1)[0]
        if root not in STRUCTURAL_ROOTS:
            violations.append(f"{path.relative_to(REPO_ROOT)}: {key}")

    assert violations == []


def test_aliases_are_globally_unique_short_names() -> None:
    aliases: dict[str, str] = {}
    violations: list[str] = []
    for path, entry in _field_entries():
        key = str(entry["key"])
        for raw_alias in entry.get("aliases") or ():
            alias = str(raw_alias)
            previous = aliases.setdefault(alias, key)
            if previous != key:
                violations.append(f"{alias}: {previous} / {key}")
            if "." in alias:
                violations.append(f"{path.relative_to(REPO_ROOT)}: dotted alias {alias}")

    assert violations == []


def test_aliases_do_not_shadow_meta_control_keys() -> None:
    registry = load_observability_taxonomy(TAXONOMY_ROOT)

    assert sorted(set(registry.field_aliases) & META_CONTROL_KEYS) == []


def test_aliases_do_not_shadow_unapproved_structural_roots() -> None:
    registry = load_observability_taxonomy(TAXONOMY_ROOT)
    shadowed = set(registry.field_aliases) & set(STRUCTURAL_ROOTS)

    assert sorted(shadowed - APPROVED_STRUCTURAL_ALIASES) == []


def test_every_field_declares_sensitive_boolean() -> None:
    missing_or_invalid: list[str] = []
    for path, entry in _field_entries():
        if not isinstance(entry.get("sensitive"), bool):
            missing_or_invalid.append(f"{path.relative_to(REPO_ROOT)}: {entry.get('key')}")

    assert missing_or_invalid == []


def test_sensitive_metadata_matches_field_entries() -> None:
    registry = load_observability_taxonomy(TAXONOMY_ROOT)
    expected_keys = {
        str(entry["key"])
        for _, entry in _field_entries()
        if bool(entry.get("sensitive"))
    }
    expected_aliases = {
        str(alias)
        for _, entry in _field_entries()
        if bool(entry.get("sensitive"))
        for alias in (entry.get("aliases") or ())
    }

    assert registry.sensitive_keys == frozenset(expected_keys)
    assert registry.sensitive_aliases == frozenset(expected_aliases)


def test_action_zones_have_zone_docs_or_are_planned() -> None:
    existing_zone_docs = {path.stem for path in ZONES_ROOT.glob("*.md")}
    violations: list[str] = []
    for action in _actions_payload()["actions"]:
        zone = str(action["zone"])
        status = str(action["status"])
        if zone not in existing_zone_docs and status != "planned":
            violations.append(f"{action['name']}: {zone}")

    assert violations == []


def test_yaml_ecs_versions_match_runtime_ecs_version() -> None:
    versions = {_actions_payload()["ecs_version"]}
    versions.update(payload["ecs_version"] for _, payload in _field_payloads())

    assert versions == {ECS_VERSION}


def test_ecs_owned_fields_exist_in_vendored_ecs_slice() -> None:
    """Срез содержит только используемые нами ECS 8.11 поля; при апгрейде ECS обновлять diff-ом."""
    ecs_fields = {
        str(entry["name"]): str(entry["type"])
        for entry in json.loads(ECS_FIELDS_SLICE.read_text(encoding="utf-8"))
    }
    violations: list[str] = []
    for path, entry in _field_entries():
        if entry["owner"] != "ecs":
            continue
        key = str(entry["key"])
        expected_type = str(entry["ecs_type"])
        actual_type = ecs_fields.get(key)
        if actual_type != expected_type:
            violations.append(
                f"{path.relative_to(REPO_ROOT)}: {key} taxonomy={expected_type} ecs={actual_type}"
            )

    assert violations == []
