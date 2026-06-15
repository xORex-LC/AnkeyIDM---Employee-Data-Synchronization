"""Юнит-тесты DI-проводки runtime источников.

Назначение:
    Проверяют, что `SourceContainer` и compatibility provider
    `PipelineContainer.row_source` строят источник через `get_source_spec()`.

Граница тестирования:
    Не прогоняют полный pipeline; только composition root seam.
"""

from __future__ import annotations

import pytest

from connector.config.models import AppConfig, ExtractConfig
from connector.delivery.cli.containers import PipelineContainer
from connector.delivery.cli.sources_container import SourceContainer
from connector.domain.transform_dsl.specs import SourceSpec
from connector.infra.sources.csv_reader import PolarsCsvRecordSource


class _DatasetSpec:
    dataset_name = "employees"

    def __init__(self, source_spec: SourceSpec) -> None:
        self._source_spec = source_spec
        self.get_source_spec_calls = 0

    def get_source_spec(self) -> SourceSpec:
        self.get_source_spec_calls += 1
        return self._source_spec


def _source_spec(path: str) -> SourceSpec:
    return SourceSpec.model_validate(
        {
            "dataset": "employees",
            "source": {
                "type": "file",
                "format": "csv",
                "location": path,
                "has_header": True,
                "options": {
                    "delimiter": ";",
                    "encoding": "utf-8-sig",
                },
            },
        }
    )


@pytest.mark.unit
def test_source_container_builds_row_source_from_source_spec(tmp_path):
    csv_path = tmp_path / "employees.csv"
    csv_path.write_text("id;name\n001;Ivan\n", encoding="utf-8")
    dataset_spec = _DatasetSpec(_source_spec(str(csv_path)))
    container = SourceContainer()
    container.app_config.override(AppConfig(extract=ExtractConfig(read_batch_size=123)))
    container.dataset_spec.override(dataset_spec)

    row_source = container.row_source()

    assert isinstance(row_source, PolarsCsvRecordSource)
    assert row_source.path == str(csv_path)
    assert row_source.has_header is True
    assert row_source.delimiter == ";"
    assert row_source.encoding == "utf-8-sig"
    assert row_source.read_batch_size == 123
    assert dataset_spec.get_source_spec_calls == 1


@pytest.mark.unit
def test_pipeline_row_source_delegates_to_sources_subcontainer(tmp_path):
    csv_path = tmp_path / "employees.csv"
    csv_path.write_text("id;name\n001;Ivan\n", encoding="utf-8")
    dataset_spec = _DatasetSpec(_source_spec(str(csv_path)))
    container = PipelineContainer()
    container.app_config.override(AppConfig(extract=ExtractConfig(read_batch_size=321)))
    container.dataset_spec.override(dataset_spec)

    row_source = container.row_source()

    assert isinstance(row_source, PolarsCsvRecordSource)
    assert row_source.path == str(csv_path)
    assert row_source.read_batch_size == 321
    assert dataset_spec.get_source_spec_calls == 1
