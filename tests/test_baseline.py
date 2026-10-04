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

"""Tests for schema-1 baseline values, canonical JSON, and file boundaries."""

from __future__ import annotations

import json
import os
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, cast

import pytest

from importtime_check import (
    Baseline,
    BaselineError,
    EnvironmentIdentity,
    SamplingPolicy,
    TargetBaseline,
    decode_baseline,
    encode_baseline,
    load_baseline,
    save_baseline,
)


def _baseline() -> Baseline:
    return Baseline(
        EnvironmentIdentity("cpython", "3.11", "win32", " AMD64 "),
        SamplingPolicy(),
        {"json": TargetBaseline(420, 25, "10.00")},
    )


def test_canonical_json_round_trip_and_copied_targets() -> None:
    source = {"json": TargetBaseline(420, 25, "10.00")}
    value = Baseline(
        EnvironmentIdentity("cpython", "3.11", "win32", " AMD64 "),
        SamplingPolicy(),
        source,
    )
    source.clear()
    raw = encode_baseline(value)
    expected = (
        b'{\n  "environment": {\n    "implementation": "cpython",\n'
        b'    "machine": "amd64",\n    "platform": "win32",\n'
        b'    "profile": "default",\n    "python": "3.11"\n  },\n'
        b'  "sampling": {\n    "samples": 5,\n'
        b'    "statistic": "upper_median",\n    "warmups": 1\n  },\n'
        b'  "schema_version": 1,\n  "targets": {\n    "json": {\n'
        b'      "baseline_cumulative_us": 420,\n'
        b'      "max_increase_percent": "10",\n'
        b'      "max_increase_us": 25\n    }\n  }\n}\n'
    )
    assert raw == expected
    assert encode_baseline(decode_baseline(raw)) == raw
    assert decode_baseline("  " + raw.decode()) == value
    assert value.environment.machine == "amd64"
    assert value.targets["json"].max_increase_percent == "10"
    with pytest.raises(TypeError):
        value.targets["other"] = TargetBaseline(1, 0, "0")  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        value.schema_version = 2  # type: ignore[misc]


@pytest.mark.parametrize("value", ("0", "0.00", "1", "1.20", "0.25"))
def test_percentage_normalization(value: str) -> None:
    normalized = {"0": "0", "0.00": "0", "1": "1", "1.20": "1.2", "0.25": "0.25"}
    assert TargetBaseline(0, 0, value).max_increase_percent == normalized[value]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("implementation", "pypy", "implementation"),
        ("python", "3.11.9", "major.minor"),
        ("python", 311, "major.minor"),
        ("platform", " ", "platform"),
        ("platform", 3, "platform"),
        ("machine", "", "machine"),
        ("machine", 3, "machine"),
        ("profile", " ", "profile"),
        ("profile", 3, "profile"),
    ),
)
def test_invalid_environment_field(field: str, value: object, message: str) -> None:
    fields: dict[str, object] = {
        "implementation": "cpython",
        "python": "3.11",
        "platform": "win32",
        "machine": "amd64",
        "profile": "default",
    }
    fields[field] = value
    with pytest.raises(ValueError, match=message):
        EnvironmentIdentity(**cast(Any, fields))


@pytest.mark.parametrize(
    ("warmups", "samples", "statistic", "message"),
    (
        (True, 5, "upper_median", "warmups"),
        (-1, 5, "upper_median", "warmups"),
        (1, False, "upper_median", "samples"),
        (1, 0, "upper_median", "samples"),
        (1, 5, "mean", "statistic"),
    ),
)
def test_invalid_sampling_policy(
    warmups: object, samples: object, statistic: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        SamplingPolicy(cast(Any, warmups), cast(Any, samples), statistic)


@pytest.mark.parametrize(
    ("baseline_us", "allowance", "percent", "message"),
    (
        (True, 0, "0", "baseline_cumulative_us"),
        (-1, 0, "0", "baseline_cumulative_us"),
        (1, False, "0", "max_increase_us"),
        (1, -1, "0", "max_increase_us"),
        (1, 0, 2, "max_increase_percent"),
        (1, 0, "-1", "max_increase_percent"),
        (1, 0, "02", "max_increase_percent"),
        (1, 0, "1e3", "max_increase_percent"),
    ),
)
def test_invalid_target_baseline(
    baseline_us: object, allowance: object, percent: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        TargetBaseline(cast(Any, baseline_us), cast(Any, allowance), cast(Any, percent))


@pytest.mark.parametrize(
    ("environment", "sampling", "targets", "version", "message"),
    (
        ("valid", "valid", "valid", 2, "schema_version"),
        ("valid", "valid", "valid", True, "schema_version"),
        ("bad", "valid", "valid", 1, "EnvironmentIdentity"),
        ("valid", "bad", "valid", 1, "SamplingPolicy"),
        ("valid", "valid", {}, 1, "non-empty mapping"),
        ("valid", "valid", {"bad-name": "valid"}, 1, "dotted"),
        ("valid", "valid", {"json": "bad"}, 1, "TargetBaseline"),
    ),
)
def test_invalid_baseline_model(
    environment: object,
    sampling: object,
    targets: object,
    version: object,
    message: str,
) -> None:
    valid = _baseline()
    env = valid.environment if environment == "valid" else environment
    policy = valid.sampling if sampling == "valid" else sampling
    target_values = (
        {
            key: valid.targets["json"] if item == "valid" else item
            for key, item in targets.items()
        }
        if isinstance(targets, dict)
        else targets
    )
    with pytest.raises(ValueError, match=message):
        Baseline(
            cast(Any, env),
            cast(Any, policy),
            cast(Any, target_values),
            cast(Any, version),
        )


@pytest.mark.parametrize(
    ("raw", "kind"),
    (
        (b"\xff", "baseline-invalid"),
        ("{", "baseline-invalid"),
        ("[]", "baseline-invalid"),
        ("{}", "schema-unsupported"),
        ('{"schema_version": true}', "schema-unsupported"),
        ('{"schema_version": 2}', "schema-unsupported"),
        ('{"schema_version": 1}', "baseline-invalid"),
        ('{"schema_version": 1, "schema_version": 1}', "baseline-invalid"),
        ('{"schema_version": NaN}', "baseline-invalid"),
    ),
)
def test_rejects_bad_document(raw: bytes | str, kind: str) -> None:
    with pytest.raises(BaselineError) as found:
        decode_baseline(raw)
    assert found.value.kind == kind


@pytest.mark.parametrize(
    ("path", "replacement"),
    (
        (("environment",), []),
        (("environment", "machine"), ""),
        (("sampling",), []),
        (("sampling", "samples"), True),
        (("targets",), []),
        (("targets", "json"), {}),
        (("targets", "json", "baseline_cumulative_us"), 1.5),
        (("targets", "json", "max_increase_percent"), "NaN"),
    ),
)
def test_rejects_invalid_nested_schema(
    path: tuple[str, ...], replacement: object
) -> None:
    document: dict[str, Any] = json.loads(encode_baseline(_baseline()))
    target: dict[str, Any] = document
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement
    with pytest.raises(BaselineError) as found:
        decode_baseline(json.dumps(document))
    assert found.value.kind == "baseline-invalid"


def test_decode_rejects_wrong_source_type() -> None:
    with pytest.raises(BaselineError, match="JSON"):
        decode_baseline(cast(Any, 23))


def test_encode_rejects_wrong_model() -> None:
    with pytest.raises(ValueError, match="Baseline"):
        encode_baseline(cast(Any, {}))


def test_file_round_trip_refuses_overwrite_then_replaces(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    value = _baseline()
    save_baseline(path, value)
    assert path.read_bytes() == encode_baseline(value)
    assert load_baseline(path) == value
    with pytest.raises(BaselineError, match="already exists") as found:
        save_baseline(path, value)
    assert found.value.kind == "io-error"
    changed = Baseline(
        value.environment, value.sampling, {"json": TargetBaseline(9, 0, "0")}
    )
    save_baseline(path, changed, replace=True)
    assert load_baseline(path) == changed
    assert not list(tmp_path.glob(".importtime-check-*.tmp"))


def test_missing_and_unreadable_paths(tmp_path: Path) -> None:
    with pytest.raises(BaselineError) as missing:
        load_baseline(tmp_path / "missing.json")
    assert missing.value.kind == "baseline-missing"
    with pytest.raises(BaselineError) as unreadable:
        load_baseline(tmp_path)
    assert unreadable.value.kind == "io-error"
    with pytest.raises(BaselineError) as unwritable:
        save_baseline(tmp_path / "absent" / "baseline.json", _baseline())
    assert unwritable.value.kind == "io-error"


def test_atomic_failure_keeps_existing_file_and_cleans_temp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "baseline.json"
    path.write_bytes(b"original")

    def fail_link(source: os.PathLike[str], target: os.PathLike[str]) -> None:
        raise OSError("link unavailable")

    monkeypatch.setattr(os, "link", fail_link)
    with pytest.raises(BaselineError, match="link unavailable") as found:
        save_baseline(path, _baseline())
    assert found.value.kind == "io-error"
    assert path.read_bytes() == b"original"
    assert not list(tmp_path.glob(".importtime-check-*.tmp"))
