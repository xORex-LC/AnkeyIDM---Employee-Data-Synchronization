"""
Назначение:
    Transform DSL: спецификации source-стадии.
"""

from __future__ import annotations

import codecs
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from connector.domain.dsl.specs._base import DslBaseModel


class CsvSourceFormat(DslBaseModel):
    """
    Назначение:
        Декларативные параметры физического CSV-формата источника.

    Контракт:
        `kind` является discriminator для `SourceFormat`. Остальные поля
        описывают только CSV-семантику и не должны выноситься на уровень
        `SourceConfig`.
    """

    kind: Literal["csv"]
    delimiter: str = ","
    encoding: str = "utf-8-sig"
    has_header: bool = False

    @field_validator("delimiter", mode="after")
    @classmethod
    def _validate_delimiter(cls, value: str) -> str:
        if value == "":
            raise ValueError("CSV delimiter must be non-empty")
        if len(value) != 1:
            raise ValueError("CSV delimiter must be exactly one character")
        return value

    @field_validator("encoding", mode="after")
    @classmethod
    def _validate_encoding(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("CSV encoding must be non-empty")
        try:
            codecs.lookup(normalized)
        except LookupError as exc:
            raise ValueError(f"CSV encoding is unknown: {normalized}") from exc
        return normalized


SourceFormat = Annotated[CsvSourceFormat, Field(discriminator="kind")]


class SourceFieldSpec(DslBaseModel):
    """
    Назначение:
        Декларативное описание поля входного источника.

    Контракт:
        `name` сейчас используется как документированное имя поля источника.
        Сопоставление source -> sink выполняется mapping DSL, а `aliases` пока
        не применяются в runtime. Поле `aliases` оставлено как точка расширения
        для будущей нормализации физических имён колонок к каноническим source
        names на source boundary. В DEC-002 `fields` остаётся advisory и не
        является runtime-валидацией записей.
    """

    name: str
    type: Literal["string", "int", "float", "bool", "object", "list"] | None = None
    required: bool = False
    nullable: bool = True
    aliases: list[str] = Field(default_factory=list)


class SourceConfig(DslBaseModel):
    """
    Назначение:
        Декларативная конфигурация источника датасета.
    """

    type: Literal["file", "db", "api"]
    location: str | None = None
    format: SourceFormat
    fields: list[SourceFieldSpec] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_shape(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        if isinstance(data.get("format"), str):
            raise ValueError(
                "source.format must use object shape: "
                "format: {kind: csv, delimiter: ..., encoding: ..., has_header: ...}"
            )
        if "options" in data:
            raise ValueError(
                "source.options is not supported; migrate CSV options into source.format"
            )
        if "has_header" in data:
            raise ValueError(
                "source.has_header is not supported; use source.format.has_header"
            )
        return data

    @model_validator(mode="after")
    def _validate_type(self) -> "SourceConfig":
        if self.type == "file":
            location = (self.location or "").strip()
            if not location:
                raise ValueError("source.location must be configured for file sources")
        return self


class SourceSpec(DslBaseModel):
    """
    Назначение:
        Декларативная спецификация extract-источника датасета.
    """

    dataset: str
    source: SourceConfig
