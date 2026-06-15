"""Юнит-тесты реестра адаптеров источников.

Назначение:
    Проверяют выбор сборщика по `(type, format)` и fail-fast поведение
    registry для ошибочной конфигурации.

Граница тестирования:
    Не тестируют физическое чтение CSV; это ответственность adapter tests.
"""

from __future__ import annotations

import pytest

from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform_dsl.specs import SourceSpec
from connector.infra.sources.factory import SourceAdapterRegistry


class _Rows:
    def __iter__(self):
        yield SourceRecord(line_no=1, record_id="line:1", values={"id": "001"})


def _source_spec(
    *,
    source_type: str = "file",
    source_format: str | None = "csv",
) -> SourceSpec:
    return SourceSpec.model_validate(
        {
            "dataset": "employees",
            "source": {
                "type": source_type,
                "format": source_format,
                "location": "employees.csv",
            },
        }
    )


@pytest.mark.unit
def test_registry_creates_source_by_type_and_format():
    registry = SourceAdapterRegistry()
    source = _Rows()

    registry.register(type="file", format="csv", builder=lambda spec: source)

    assert registry.create(_source_spec()) is source


@pytest.mark.unit
def test_registry_normalizes_registered_key():
    registry = SourceAdapterRegistry()
    source = _Rows()

    registry.register(type=" FILE ", format=" CSV ", builder=lambda spec: source)

    assert registry.create(_source_spec()) is source


@pytest.mark.unit
def test_registry_rejects_duplicate_key():
    registry = SourceAdapterRegistry()
    registry.register(type="file", format="csv", builder=lambda spec: _Rows())

    with pytest.raises(ValueError, match="already registered"):
        registry.register(type="file", format="csv", builder=lambda spec: _Rows())


@pytest.mark.unit
def test_registry_rejects_unknown_source_adapter():
    registry = SourceAdapterRegistry()

    with pytest.raises(ValueError, match="Unsupported source adapter"):
        registry.create(_source_spec(source_format="json"))
