"""Архитектурные guard-тесты для границ observability logging layer."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from connector.common.observability import (
    ObservabilityEvent,
    ObservabilityEventSink,
    PipelineLifecycleEvents,
    RuntimeLifecycleEvents,
)
from connector.infra.logging.ecs import STRUCTURAL_ROOTS

pytestmark = pytest.mark.architecture

REPO_ROOT = Path(__file__).resolve().parents[2]
CONNECTOR_ROOT = REPO_ROOT / "connector"
COMMON_OBSERVABILITY_ROOT = CONNECTOR_ROOT / "common" / "observability"
INFRA_LOGGING_ROOT = CONNECTOR_ROOT / "infra" / "logging"
INFRA_OBSERVABILITY_ROOT = CONNECTOR_ROOT / "infra" / "observability"
TAXONOMY_FIELDS_ROOT = COMMON_OBSERVABILITY_ROOT / "taxonomy" / "fields"
TAXONOMY_ACTIONS_FILE = COMMON_OBSERVABILITY_ROOT / "taxonomy" / "actions.yaml"
LOGGING_ADAPTER_ROOTS = (
    INFRA_LOGGING_ROOT / "lifecycle.py",
    INFRA_LOGGING_ROOT / "zones",
)
CALLSITE_MAP_FILE = (
    REPO_ROOT
    / "docs"
    / "dev"
    / "layers"
    / "observability"
    / "ecs-logging-taxonomy"
    / "callsite-map.md"
)
ACTION_LITERAL_RE = re.compile(r"`([a-z0-9]+(?:-[a-z0-9]+)*)`")

EXPECTED_STRUCTURAL_ROOTS = frozenset(
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

ALLOWED_ECS_TRANSFORM_IMPORTS = {
    "connector/infra/logging/runtime.py",
}
ECS_TRANSFORM_APIS = frozenset({"make_ecs_transform"})
KNOWN_USECASE_LOGGING_BACKEND_IMPORTS = frozenset(
    {
        "connector/usecases/management/vault/usecase.py: structlog",
        "connector/usecases/resolve_usecase.py: structlog",
    }
)
COMMON_OBSERVABILITY_FORBIDDEN_IMPORTS = frozenset(
    {
        "dependency_injector",
        "logging",
        "pydantic",
        "structlog",
        "yaml",
    }
)
COMMON_OBSERVABILITY_FORBIDDEN_PREFIXES = (
    "connector.delivery",
    "connector.domain",
    "connector.infra",
    "connector.usecases",
    "dependency_injector.",
    "logging.",
    "pydantic.",
    "structlog.",
    "yaml.",
)


def _python_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
    return modules


def _import_froms(path: Path) -> list[tuple[str, list[str]]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[tuple[str, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            result.append((node.module or "", [alias.name for alias in node.names]))
    return result


def _field_entries() -> list[tuple[Path, dict[str, Any]]]:
    entries: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(TAXONOMY_FIELDS_ROOT.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entries.extend((path, entry) for entry in payload.get("fields") or ())
    return entries


def _action_names() -> frozenset[str]:
    payload = yaml.safe_load(TAXONOMY_ACTIONS_FILE.read_text(encoding="utf-8")) or {}
    return frozenset(str(entry["name"]) for entry in payload.get("actions") or ())


def _logging_adapter_files() -> list[Path]:
    files: list[Path] = []
    for root in LOGGING_ADAPTER_ROOTS:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(_python_files(root))
    return sorted(files)


def _observability_event_action_literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    actions: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Name) or func.id != "ObservabilityEvent":
            continue
        for keyword in node.keywords:
            if keyword.arg == "action" and isinstance(keyword.value, ast.Constant):
                if isinstance(keyword.value.value, str):
                    actions.append(keyword.value.value)
    return actions


def _callsite_map_actions() -> frozenset[str]:
    actions: set[str] = set()
    for line in CALLSITE_MAP_FILE.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or "`" not in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        actions.update(ACTION_LITERAL_RE.findall(cells[3]))
    return frozenset(actions)


def test_event_contracts_live_in_common_observability() -> None:
    assert ObservabilityEvent.__module__ == "connector.common.observability.events"
    assert ObservabilityEventSink.__module__ == "connector.common.observability.ports"
    assert RuntimeLifecycleEvents.__module__ == "connector.common.observability.ports"
    assert PipelineLifecycleEvents.__module__ == "connector.common.observability.ports"


def test_common_observability_contracts_do_not_import_infra_or_delivery() -> None:
    violations: list[str] = []
    for path in _python_files(COMMON_OBSERVABILITY_ROOT):
        if "taxonomy" in path.parts:
            continue
        for module in _imports(path):
            if module in COMMON_OBSERVABILITY_FORBIDDEN_IMPORTS or module.startswith(
                COMMON_OBSERVABILITY_FORBIDDEN_PREFIXES
            ):
                violations.append(f"{_rel(path)}: {module}")

    assert violations == [], (
        "common observability contracts must stay dependency-light and "
        "runtime-neutral:\n"
        + "\n".join(violations)
    )


def test_ecs_transform_is_imported_only_by_logging_runtime() -> None:
    violations: list[str] = []
    for path in _python_files(CONNECTOR_ROOT):
        rel = _rel(path)
        if (
            rel in ALLOWED_ECS_TRANSFORM_IMPORTS
            or rel == "connector/infra/logging/ecs.py"
        ):
            continue
        for module, names in _import_froms(path):
            imported_apis = sorted(ECS_TRANSFORM_APIS.intersection(names))
            if module == "connector.infra.logging.ecs" and imported_apis:
                violations.append(
                    f"{rel}: from {module} import {', '.join(imported_apis)}"
                )

    assert violations == [], (
        "ECS transform APIs must remain owned by logging runtime:\n"
        + "\n".join(violations)
    )


def test_usecases_do_not_add_new_logging_backend_imports() -> None:
    current: set[str] = set()
    usecases_root = CONNECTOR_ROOT / "usecases"
    for path in _python_files(usecases_root):
        rel = _rel(path)
        for module in _imports(path):
            if module == "structlog" or module.startswith("structlog."):
                current.add(f"{rel}: structlog")
            if module.startswith("connector.infra.logging"):
                current.add(f"{rel}: {module}")

    assert current == KNOWN_USECASE_LOGGING_BACKEND_IMPORTS, (
        "Usecases must not add direct logging backend imports. "
        "Remove fixed legacy entries from KNOWN_USECASE_LOGGING_BACKEND_IMPORTS "
        "when migrating them to observability ports.\nCurrent:\n"
        + "\n".join(sorted(current))
    )


def test_domain_does_not_import_logging_backend() -> None:
    violations: list[str] = []
    domain_root = CONNECTOR_ROOT / "domain"
    for path in _python_files(domain_root):
        rel = _rel(path)
        for module in _imports(path):
            if module == "structlog" or module.startswith("structlog."):
                violations.append(f"{rel}: structlog")
            if module.startswith("connector.infra.logging"):
                violations.append(f"{rel}: {module}")

    assert violations == [], (
        "Domain must not import logging backend APIs:\n" + "\n".join(violations)
    )


def test_infra_logging_and_observability_artifacts_stay_decoupled() -> None:
    violations: list[str] = []
    boundaries = (
        (INFRA_LOGGING_ROOT, "connector.infra.observability"),
        (INFRA_OBSERVABILITY_ROOT, "connector.infra.logging"),
    )
    for root, forbidden_prefix in boundaries:
        for path in _python_files(root):
            rel = _rel(path)
            for module in _imports(path):
                if module == forbidden_prefix or module.startswith(
                    f"{forbidden_prefix}."
                ):
                    violations.append(f"{rel}: {module}")

    assert violations == [], (
        "Logging runtime and observability artifact lifecycle must stay decoupled:\n"
        + "\n".join(violations)
    )


def test_reserved_structural_roots_are_complete_and_explicit() -> None:
    assert STRUCTURAL_ROOTS == EXPECTED_STRUCTURAL_ROOTS


def test_taxonomy_field_roots_are_allowed_structural_roots() -> None:
    violations: list[str] = []
    for path, entry in _field_entries():
        key = str(entry["key"])
        root = key.split(".", 1)[0] if key != "@timestamp" else "@timestamp"
        if root not in EXPECTED_STRUCTURAL_ROOTS:
            violations.append(f"{_rel(path)}: {key}")

    assert violations == [], (
        "taxonomy field keys must use approved ECS/project roots:\n"
        + "\n".join(violations)
    )


def test_taxonomy_field_aliases_are_short_unique_names() -> None:
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
                violations.append(f"{_rel(path)}: alias must not be dotted: {alias}")

    assert violations == [], (
        "taxonomy aliases must be short, unique names:\n" + "\n".join(violations)
    )


def test_logging_adapter_actions_exist_in_taxonomy() -> None:
    known_actions = _action_names()
    violations: list[str] = []
    for path in _logging_adapter_files():
        for action in _observability_event_action_literals(path):
            if action not in known_actions:
                violations.append(f"{_rel(path)}: {action}")

    assert violations == [], (
        "ObservabilityEvent action literals in logging adapters must exist in "
        "actions.yaml:\n"
        + "\n".join(violations)
    )


def test_logging_adapters_do_not_import_taxonomy_registry() -> None:
    violations: list[str] = []
    for path in _logging_adapter_files():
        for module in _imports(path):
            if module == "connector.infra.logging.taxonomy":
                violations.append(f"{_rel(path)}: {module}")

    assert violations == [], (
        "Logging adapters must stay semantic and must not import taxonomy registry:\n"
        + "\n".join(violations)
    )


def test_callsite_map_actions_are_subset_of_taxonomy_actions() -> None:
    unknown = sorted(_callsite_map_actions() - _action_names())

    assert unknown == [], (
        "callsite-map.md must not reference actions absent from actions.yaml:\n"
        + "\n".join(unknown)
    )
