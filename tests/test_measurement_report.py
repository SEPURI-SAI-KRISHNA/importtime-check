# Copyright 2026 importtime-check contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Strict, bounded reading of version-1 measurement artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from importtime_check import (
    MeasurementReport,
    MeasurementReportError,
    ReportIdentity,
    ReportTarget,
    SamplingPolicy,
    decode_measurement_report,
    load_measurement_report,
)


def _document() -> dict[str, Any]:
    return {
        "environment": {
            "implementation": "cpython",
            "machine": "amd64",
            "platform": "win32",
            "python": "3.11",
        },
        "report_type": "measurement",
        "report_version": 1,
        "sampling": {"samples": 3, "statistic": "upper_median", "warmups": 1},
        "targets": {
            "json": {
                "samples_us": [40, 42, 44],
                "upper_median_us": 42,
                "warmups_us": [45],
            },
            "email": {
                "samples_us": [8, 10, 12],
                "upper_median_us": 10,
                "warmups_us": [13],
            },
        },
    }


def _raw(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _report() -> MeasurementReport:
    return decode_measurement_report(_raw(_document()))


def test_decodes_version_one_with_sorted_immutable_targets_and_digest() -> None:
    payload = _raw(_document())
    report = decode_measurement_report(payload)
    assert report == decode_measurement_report(payload.decode("utf-8"))
    assert report.report_version == 1
    assert report.environment == ReportIdentity("cpython", "3.11", "win32", "amd64")
    assert report.sampling == SamplingPolicy(1, 3)
    assert tuple(report.targets) == ("email", "json")
    assert report.targets["email"] == ReportTarget((13,), (8, 10, 12), 10)
    assert report.source_sha256 == hashlib.sha256(payload).hexdigest()
    assert (
        decode_measurement_report(b" " + payload).source_sha256 != report.source_sha256
    )
    with pytest.raises(TypeError):
        report.targets["other"] = report.targets["email"]  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        report.report_version = 2  # type: ignore[misc]


def test_model_copies_mutable_input_and_normalizes_machine() -> None:
    samples = [1, 2, 3]
    warmups = [4]
    target = ReportTarget(cast(Any, warmups), cast(Any, samples), 2)
    samples.append(5)
    warmups.clear()
    assert target.samples_us == (1, 2, 3)
    assert target.warmups_us == (4,)
    targets = {"json": target}
    report = MeasurementReport(
        ReportIdentity("cpython", "3.11", "win32", " AMD64 "),
        SamplingPolicy(1, 3),
        targets,
        "a" * 64,
    )
    targets.clear()
    assert report.environment.machine == "amd64"
    assert tuple(report.targets) == ("json",)
    with pytest.raises(FrozenInstanceError):
        target.upper_median_us = 3  # type: ignore[misc]


def test_error_keeps_safe_structured_diagnostics() -> None:
    error = MeasurementReportError(
        "cohort-mismatch",
        "reports differ",
        source_index=2,
        differing_fields=("sampling.samples", "environment.python"),
    )
    assert error.kind == "cohort-mismatch"
    assert error.source_index == 2
    assert error.differing_fields == ("environment.python", "sampling.samples")
    assert str(error) == "reports differ"
    assert MeasurementReportError("report-invalid", "bad").source_index is None


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("implementation", "pypy"),
        ("python", "3.11.9"),
        ("platform", " "),
        ("machine", ""),
    ),
)
def test_report_identity_reuses_safe_environment_validation(
    field: str, value: str
) -> None:
    fields = dict(
        implementation="cpython", python="3.11", platform="win32", machine="amd64"
    )
    fields[field] = value
    with pytest.raises(ValueError):
        ReportIdentity(**fields)


@pytest.mark.parametrize(
    ("warmups", "samples", "median"),
    (
        ("bad", [1], 1),
        ([], "bad", 1),
        ([1] * 101, [1], 1),
        ([], [], 1),
        ([], [1] * 1001, 1),
        ([], [True], 1),
        ([], [-1], 1),
        ([], [2**63], 1),
        ([], [1], False),
        ([], [1, 2], 1),
    ),
)
def test_report_target_rejects_invalid_direct_construction(
    warmups: object, samples: object, median: object
) -> None:
    with pytest.raises(ValueError):
        ReportTarget(cast(Any, warmups), cast(Any, samples), cast(Any, median))


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("report_version", True),
        ("report_version", 2),
        ("environment", "bad"),
        ("sampling", "bad"),
        ("sampling", SamplingPolicy(101, 1)),
        ("sampling", SamplingPolicy(0, 1001)),
        ("targets", []),
        ("targets", {}),
        ("targets", {f"m{index}": ReportTarget((), (1,), 1) for index in range(129)}),
        ("targets", {"bad-name": ReportTarget((), (1,), 1)}),
        ("targets", {"json": "bad"}),
        ("targets", {"json": ReportTarget((), (1, 2, 3), 2)}),
        ("targets", {"json": ReportTarget((1,), (1,), 1)}),
        ("source_sha256", 12),
        ("source_sha256", "A" * 64),
    ),
)
def test_report_model_rejects_invalid_direct_construction(
    field: str, value: object
) -> None:
    fields: dict[str, Any] = {
        "environment": ReportIdentity("cpython", "3.11", "win32", "amd64"),
        "sampling": SamplingPolicy(0, 1),
        "targets": {"json": ReportTarget((), (1,), 1)},
        "source_sha256": "a" * 64,
        "report_version": 1,
    }
    fields[field] = value
    with pytest.raises(ValueError):
        MeasurementReport(**fields)


@pytest.mark.parametrize(
    ("raw", "kind"),
    (
        (23, "report-invalid"),
        ("\ud800", "report-invalid"),
        (b"\xff", "report-invalid"),
        pytest.param("x" * (2 * 1024 * 1024 + 1), "report-limit", id="oversized-text"),
        pytest.param("é" * (1024 * 1024 + 1), "report-limit", id="oversized-utf8"),
        pytest.param(
            b" " * (2 * 1024 * 1024 + 1), "report-limit", id="oversized-bytes"
        ),
    ),
)
def test_rejects_invalid_source_or_size(raw: object, kind: str) -> None:
    with pytest.raises(MeasurementReportError) as found:
        decode_measurement_report(cast(Any, raw))
    assert found.value.kind == kind


@pytest.mark.parametrize(
    ("raw", "kind"),
    (
        ("{", "report-invalid"),
        ("[]", "report-invalid"),
        (
            '{"report_type": "measurement", "report_version": 1, "report_version": 1}',
            "report-invalid",
        ),
        ('{"report_type": "measurement", "report_version": NaN}', "report-invalid"),
        ('{"report_type": "measurement", "report_version": 1.0}', "report-invalid"),
        ('{"schema_version": 1}', "report-invalid"),
        ('{"report_type": "check", "report_version": 1}', "report-invalid"),
        ('{"report_type": "measurement"}', "report-unsupported"),
        (
            '{"report_type": "measurement", "report_version": true}',
            "report-unsupported",
        ),
        ('{"report_type": "measurement", "report_version": 2}', "report-unsupported"),
        ('{"report_type": "measurement", "report_version": 1}', "report-invalid"),
    ),
)
def test_rejects_malformed_or_wrong_document(raw: str, kind: str) -> None:
    with pytest.raises(MeasurementReportError) as found:
        decode_measurement_report(raw)
    assert found.value.kind == kind


@pytest.mark.parametrize(
    ("path", "replacement", "kind"),
    (
        (("environment",), [], "report-invalid"),
        (("environment", "profile"), "default", "report-invalid"),
        (("environment", "python"), "3.11.9", "report-invalid"),
        (("sampling",), [], "report-invalid"),
        (("sampling", "statistic"), "mean", "report-invalid"),
        (("sampling", "samples"), False, "report-invalid"),
        (("sampling", "samples"), 0, "report-invalid"),
        (("sampling", "samples"), 1001, "report-limit"),
        (("sampling", "warmups"), 101, "report-limit"),
        (("targets",), [], "report-invalid"),
        (("targets",), {}, "report-invalid"),
        (
            ("targets", "bad-name"),
            {"warmups_us": [1], "samples_us": [1, 2, 3], "upper_median_us": 2},
            "report-invalid",
        ),
        (("targets", "json"), {}, "report-invalid"),
        (("targets", "json", "warmups_us"), [1] * 101, "report-limit"),
        (("targets", "json", "samples_us"), [1] * 1001, "report-limit"),
        (("targets", "json", "samples_us"), [1, 2], "report-invalid"),
        (("targets", "json", "samples_us"), [1, True, 3], "report-invalid"),
        (("targets", "json", "upper_median_us"), 43, "report-invalid"),
        (("targets", "json", "upper_median_us"), 2**63, "report-invalid"),
        (("targets", "json", "warmups_us"), [], "report-invalid"),
    ),
)
def test_rejects_invalid_nested_content(
    path: tuple[str, ...], replacement: object, kind: str
) -> None:
    document = _document()
    current: dict[str, Any] = document
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = replacement
    with pytest.raises(MeasurementReportError) as found:
        decode_measurement_report(_raw(document))
    assert found.value.kind == kind
    assert "private" not in str(found.value)


def test_rejects_extra_root_fields_and_too_many_targets() -> None:
    document = _document()
    document["extra"] = "not a report field"
    with pytest.raises(MeasurementReportError) as extra:
        decode_measurement_report(_raw(document))
    assert extra.value.kind == "report-invalid"
    document = _document()
    document["targets"] = {
        f"m{index}": {"warmups_us": [1], "samples_us": [1, 2, 3], "upper_median_us": 2}
        for index in range(129)
    }
    with pytest.raises(MeasurementReportError) as targets:
        decode_measurement_report(_raw(document))
    assert targets.value.kind == "report-limit"


def test_excessive_json_nesting_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_json(*args: object, **kwargs: object) -> None:
        raise RecursionError("private path")

    monkeypatch.setattr(json, "loads", fail_json)
    with pytest.raises(MeasurementReportError) as found:
        decode_measurement_report(b"{}")
    assert found.value.kind == "report-invalid"
    assert "private" not in str(found.value)


def test_loads_file_and_reports_safe_missing_and_nonregular_errors(
    tmp_path: Path,
) -> None:
    path = tmp_path / "measurement.json"
    path.write_bytes(_raw(_document()))
    assert load_measurement_report(path) == _report()
    assert load_measurement_report(str(path)) == _report()
    with pytest.raises(MeasurementReportError) as missing:
        load_measurement_report(tmp_path / "private-missing.json")
    assert missing.value.kind == "report-missing"
    assert "private" not in str(missing.value)
    with pytest.raises(MeasurementReportError) as directory:
        load_measurement_report(tmp_path)
    assert directory.value.kind == "io-error"
    with pytest.raises(MeasurementReportError) as invalid_path:
        load_measurement_report(cast(Any, object()))
    assert invalid_path.value.kind == "io-error"
    path.write_bytes(b'{"report_type":')
    with pytest.raises(MeasurementReportError) as truncated:
        load_measurement_report(path)
    assert truncated.value.kind == "report-invalid"


def test_loader_rejects_a_symlink_mode_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "measurement.json"
    path.write_bytes(_raw(_document()))
    original_lstat = Path.lstat

    def link_mode(self: Path) -> Any:
        found = original_lstat(self)
        return SimpleNamespace(
            st_mode=stat.S_IFLNK,
            st_size=found.st_size,
            st_dev=found.st_dev,
            st_ino=found.st_ino,
        )

    monkeypatch.setattr(Path, "lstat", link_mode)
    with pytest.raises(MeasurementReportError) as found:
        load_measurement_report(path)
    assert found.value.kind == "io-error"
    assert "non-symlink" in str(found.value)


def test_file_limits_before_and_after_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "huge.json"
    with path.open("wb") as stream:
        stream.truncate(2 * 1024 * 1024 + 1)
    with pytest.raises(MeasurementReportError) as initial:
        load_measurement_report(path)
    assert initial.value.kind == "report-limit"

    original_lstat = Path.lstat

    def stale_size(self: Path) -> Any:
        found = original_lstat(self)
        return SimpleNamespace(
            st_mode=found.st_mode,
            st_size=0,
            st_dev=found.st_dev,
            st_ino=found.st_ino,
        )

    monkeypatch.setattr(Path, "lstat", stale_size)
    with pytest.raises(MeasurementReportError) as grown:
        load_measurement_report(path)
    assert grown.value.kind == "report-limit"


@pytest.mark.parametrize("changed_mode", (False, True))
def test_file_changed_during_open_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, changed_mode: bool
) -> None:
    path = tmp_path / "measurement.json"
    path.write_bytes(_raw(_document()))
    original_fstat = os.fstat

    def changed(fd: int) -> Any:
        found = original_fstat(fd)
        return SimpleNamespace(
            st_mode=stat.S_IFDIR if changed_mode else found.st_mode,
            st_size=found.st_size,
            st_dev=found.st_dev,
            st_ino=found.st_ino + 1,
        )

    monkeypatch.setattr(os, "fstat", changed)
    with pytest.raises(MeasurementReportError) as found:
        load_measurement_report(path)
    assert found.value.kind == "io-error"
    assert "changed during open" in str(found.value)


def test_file_read_error_does_not_expose_private_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "measurement.json"
    path.write_bytes(_raw(_document()))

    def fail_open(self: Path, *args: object, **kwargs: object) -> Any:
        raise OSError("C:\\private\\secret.json")

    monkeypatch.setattr(Path, "open", fail_open)
    with pytest.raises(MeasurementReportError) as found:
        load_measurement_report(path)
    assert found.value.kind == "io-error"
    assert "private" not in str(found.value)
