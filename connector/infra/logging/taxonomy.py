"""Загрузка и валидация ECS logging taxonomy.

Модуль является trust-boundary слоем для machine-readable YAML taxonomy. Он
читает `actions.yaml` и `fields/*.yaml`, валидирует их через Pydantic-модели и
собирает immutable registry для runtime processor-ов observability logging.

Границы ответственности:
    - Валидировать форму YAML taxonomy на входе в runtime.
    - Строить быстрые lookup-структуры для aliases, fields и actions.
    - Давать fail-safe empty registry для degraded logging mode.

Вне ответственности:
    - Рендеринг event dictionaries в ECS JSON.
    - Выбор момента эмиссии observability events.
    - Runtime redaction значений sensitive-полей.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from connector.common.observability.events import EventKind, LogLevel


TAXONOMY_ROOT = (
    Path(__file__).resolve().parents[2] / "common" / "observability" / "taxonomy"
)

ActionLevelName = Literal["trace", "debug", "info", "warning", "error", "critical"]
ActionOutcomePolicy = Literal["none", "always", "on_completion", "success", "unknown"]
ActionKindName = Literal["event", "metric", "state"]
ActionStatus = Literal["planned"]
ActionBucket = Literal["milestone", "decision", "diagnostic"]
FieldEcsType = Literal["keyword", "long", "float", "boolean", "date", "text", "ip", "object"]
FieldOwner = Literal["ecs", "nexus", "labels"]
FieldTier = Literal["core", "extended", "trace"]

_ACTION_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class TaxonomyLoadError(RuntimeError):
    """Ошибка загрузки или валидации observability taxonomy."""


class ActionTaxonomyEntry(BaseModel):
    """Одна запись `event.action` из `actions.yaml`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    zone: str
    bucket: ActionBucket
    default_level: ActionLevelName
    outcome: ActionOutcomePolicy
    kind: ActionKindName
    status: ActionStatus
    required_fields: tuple[str, ...] = Field(default_factory=tuple)
    levels: tuple[ActionLevelName, ...] = Field(default_factory=tuple)
    emission_point: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _validate_action_name(cls, value: str) -> str:
        if not _ACTION_NAME_RE.fullmatch(value):
            raise ValueError(f"action name must be kebab-case: {value!r}")
        return value


class ActionTaxonomyDocument(BaseModel):
    """Корневой документ `actions.yaml`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int
    ecs_version: str
    actions: tuple[ActionTaxonomyEntry, ...] = Field(default_factory=tuple)


class FieldTaxonomyEntry(BaseModel):
    """Одна canonical field запись из `fields/*.yaml`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    ecs_type: FieldEcsType
    owner: FieldOwner
    tier: FieldTier
    sensitive: bool
    aliases: tuple[str, ...] = Field(default_factory=tuple)
    description: str | None = None

    @field_validator("aliases")
    @classmethod
    def _validate_aliases(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        dotted = [alias for alias in value if "." in alias]
        if dotted:
            raise ValueError(f"aliases must be short names, got dotted aliases: {dotted}")
        return value


class FieldTaxonomyDocument(BaseModel):
    """Корневой документ одного `fields/*.yaml` файла."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int
    ecs_version: str
    fields: tuple[FieldTaxonomyEntry, ...] = Field(default_factory=tuple)


@dataclass(frozen=True)
class ObservabilityTaxonomyRegistry:
    """Immutable lookup registry для ECS logging taxonomy."""

    ecs_version: str
    actions: Mapping[str, ActionTaxonomyEntry]
    fields: Mapping[str, FieldTaxonomyEntry]
    field_aliases: Mapping[str, str]
    sensitive_keys: frozenset[str]
    sensitive_aliases: frozenset[str]
    degraded_reason: str | None = None

    @property
    def action_names(self) -> frozenset[str]:
        """Вернуть все зарегистрированные `event.action` имена."""
        return frozenset(self.actions)

    @property
    def canonical_field_keys(self) -> frozenset[str]:
        """Вернуть все canonical dotted field keys."""
        return frozenset(self.fields)

    def action(self, name: str) -> ActionTaxonomyEntry | None:
        """Найти action entry без исключения для unknown action."""
        return self.actions.get(name)

    def default_level_for(self, action: str) -> LogLevel | None:
        """Вернуть runtime log level для action, если он известен registry."""
        entry = self.action(action)
        if entry is None:
            return None
        if entry.default_level == "trace":
            return LogLevel.DEBUG
        return LogLevel(entry.default_level)

    def kind_for(self, action: str) -> EventKind | None:
        """Вернуть event kind для action, если он известен registry."""
        entry = self.action(action)
        if entry is None:
            return None
        return EventKind(entry.kind)


def load_observability_taxonomy(
    taxonomy_root: Path | str | None = None,
) -> ObservabilityTaxonomyRegistry:
    """Загрузить и валидировать YAML taxonomy из каталога observability."""
    root = Path(taxonomy_root) if taxonomy_root is not None else TAXONOMY_ROOT
    try:
        return _build_registry(
            actions=_load_actions_document(root / "actions.yaml"),
            field_documents=[
                _load_field_document(path)
                for path in sorted((root / "fields").glob("*.yaml"))
            ],
        )
    except (OSError, ValidationError, ValueError, TypeError) as exc:
        raise TaxonomyLoadError(f"Failed to load observability taxonomy: {exc}") from exc


def empty_observability_taxonomy(
    *, reason: str | None = None, ecs_version: str = "8.11"
) -> ObservabilityTaxonomyRegistry:
    """Создать пустой registry для fail-safe degraded logging mode."""
    return ObservabilityTaxonomyRegistry(
        ecs_version=ecs_version,
        actions=MappingProxyType({}),
        fields=MappingProxyType({}),
        field_aliases=MappingProxyType({}),
        sensitive_keys=frozenset(),
        sensitive_aliases=frozenset(),
        degraded_reason=reason,
    )


def _load_actions_document(path: Path) -> ActionTaxonomyDocument:
    payload = _load_yaml_mapping(path)
    return ActionTaxonomyDocument.model_validate(payload)


def _load_field_document(path: Path) -> FieldTaxonomyDocument:
    payload = _load_yaml_mapping(path)
    return FieldTaxonomyDocument.model_validate(payload)


def _load_yaml_mapping(path: Path) -> Mapping[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a YAML mapping")
    return payload


def _build_registry(
    *,
    actions: ActionTaxonomyDocument,
    field_documents: list[FieldTaxonomyDocument],
) -> ObservabilityTaxonomyRegistry:
    fields_by_key: dict[str, FieldTaxonomyEntry] = {}
    aliases: dict[str, str] = {}
    sensitive_keys: set[str] = set()
    sensitive_aliases: set[str] = set()
    ecs_versions = {actions.ecs_version}

    for document in field_documents:
        ecs_versions.add(document.ecs_version)
        for entry in document.fields:
            previous_field = fields_by_key.setdefault(entry.key, entry)
            if previous_field is not entry:
                raise ValueError(f"Duplicate field key: {entry.key}")
            if entry.sensitive:
                sensitive_keys.add(entry.key)
                sensitive_aliases.update(entry.aliases)
            for alias in entry.aliases:
                previous_key = aliases.setdefault(alias, entry.key)
                if previous_key != entry.key:
                    raise ValueError(
                        f"Field alias {alias!r} maps to both {previous_key!r} "
                        f"and {entry.key!r}"
                    )

    actions_by_name: dict[str, ActionTaxonomyEntry] = {}
    for action_entry in actions.actions:
        previous_action = actions_by_name.setdefault(action_entry.name, action_entry)
        if previous_action is not action_entry:
            raise ValueError(f"Duplicate action name: {action_entry.name}")

    if len(ecs_versions) != 1:
        raise ValueError(f"Taxonomy ECS versions differ: {sorted(ecs_versions)}")

    return ObservabilityTaxonomyRegistry(
        ecs_version=actions.ecs_version,
        actions=MappingProxyType(actions_by_name),
        fields=MappingProxyType(fields_by_key),
        field_aliases=MappingProxyType(aliases),
        sensitive_keys=frozenset(sensitive_keys),
        sensitive_aliases=frozenset(sensitive_aliases),
    )


__all__ = [
    "ActionTaxonomyDocument",
    "ActionTaxonomyEntry",
    "FieldTaxonomyDocument",
    "FieldTaxonomyEntry",
    "ObservabilityTaxonomyRegistry",
    "TAXONOMY_ROOT",
    "TaxonomyLoadError",
    "empty_observability_taxonomy",
    "load_observability_taxonomy",
]
