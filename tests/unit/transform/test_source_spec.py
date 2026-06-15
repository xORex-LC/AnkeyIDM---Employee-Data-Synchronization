from __future__ import annotations

from pathlib import Path

import pytest

from connector.common.runtime_paths import RuntimePathOverrides
from connector.domain.dsl.loader import configure_runtime_paths
from connector.domain.transform_dsl import (
    load_source_spec_for_dataset,
    resolve_source_location,
)
from connector.domain.transform_dsl.specs import CsvSourceFormat, SourceSpec
from tests.runtime_test_support import tracked_employees_runtime_roots


def test_load_source_spec_for_dataset(employees_registry_path) -> None:
    spec = load_source_spec_for_dataset("employees")
    assert spec.dataset == "employees"
    assert spec.source.type == "file"
    assert spec.source.format.kind == "csv"
    assert spec.source.location == "source_employees_example_1.csv"
    assert isinstance(spec.source.format, CsvSourceFormat)
    assert spec.source.format.delimiter
    assert spec.source.format.encoding


def test_source_spec_csv_format_defaults_to_current_runtime_values() -> None:
    spec = SourceSpec.model_validate(
        {
            "dataset": "employees",
            "source": {
                "type": "file",
                "format": {"kind": "csv"},
                "location": "/tmp/employees.csv",
            },
        }
    )

    assert spec.source.format.delimiter == ","
    assert spec.source.format.encoding == "utf-8-sig"
    assert spec.source.format.has_header is False


def test_source_spec_rejects_invalid_csv_delimiter() -> None:
    with pytest.raises(ValueError, match="CSV delimiter must be exactly one character"):
        SourceSpec.model_validate(
            {
                "dataset": "employees",
                "source": {
                    "type": "file",
                    "format": {
                        "kind": "csv",
                        "delimiter": ";;",
                        "encoding": "utf-8",
                    },
                    "location": "/tmp/employees.csv",
                },
            }
        )


def test_source_spec_rejects_unknown_csv_encoding() -> None:
    with pytest.raises(ValueError, match="CSV encoding is unknown"):
        SourceSpec.model_validate(
            {
                "dataset": "employees",
                "source": {
                    "type": "file",
                    "format": {
                        "kind": "csv",
                        "delimiter": ";",
                        "encoding": "not-a-real-encoding",
                    },
                    "location": "/tmp/employees.csv",
                },
            }
        )


def test_source_spec_rejects_unknown_format_kind() -> None:
    with pytest.raises(ValueError, match="Input tag 'cvs'"):
        SourceSpec.model_validate(
            {
                "dataset": "employees",
                "source": {
                    "type": "file",
                    "format": {"kind": "cvs"},
                    "location": "/tmp/employees.csv",
                },
            }
        )


def test_source_spec_rejects_legacy_string_format() -> None:
    with pytest.raises(ValueError, match="source.format must use object shape"):
        SourceSpec.model_validate(
            {
                "dataset": "employees",
                "source": {
                    "type": "file",
                    "format": "csv",
                    "location": "/tmp/employees.csv",
                },
            }
        )


def test_source_spec_rejects_legacy_options() -> None:
    with pytest.raises(ValueError, match="source.options is not supported"):
        SourceSpec.model_validate(
            {
                "dataset": "employees",
                "source": {
                    "type": "file",
                    "format": {"kind": "csv"},
                    "location": "/tmp/employees.csv",
                    "options": {"delimiter": ";"},
                },
            }
        )


def test_source_spec_rejects_legacy_top_level_has_header() -> None:
    with pytest.raises(ValueError, match="source.has_header is not supported"):
        SourceSpec.model_validate(
            {
                "dataset": "employees",
                "source": {
                    "type": "file",
                    "format": {"kind": "csv"},
                    "location": "/tmp/employees.csv",
                    "has_header": True,
                },
            }
        )


def test_resolve_source_location_uses_runtime_source_data_root(
    tmp_path: Path,
    employees_registry_path,
) -> None:
    roots = tracked_employees_runtime_roots()
    configure_runtime_paths(
        RuntimePathOverrides(
            datasets_root=roots["datasets_root"],
            dictionary_specs_root=roots["dictionary_specs_root"],
            dictionary_data_root=roots["dictionary_data_root"],
            source_data_root=tmp_path / "custom-sources",
            source_projection_root=roots["source_projection_root"],
            target_projection_root=roots["target_projection_root"],
        )
    )
    spec = load_source_spec_for_dataset("employees")
    try:
        assert resolve_source_location(spec) == str(
            (tmp_path / "custom-sources" / "source_employees_example_1.csv").resolve()
        )
    finally:
        configure_runtime_paths(None)


def test_source_spec_requires_location_for_file_sources() -> None:
    with pytest.raises(ValueError, match="source.location must be configured"):
        SourceSpec.model_validate(
            {
                "dataset": "employees",
                "source": {
                    "type": "file",
                    "format": {"kind": "csv"},
                },
            }
        )
