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

"""Bounded, strict decoding of version-1 measurement artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, cast

from ._baseline import EnvironmentIdentity, SamplingPolicy
from ._measurement import _validate_module_name

_MAX_REPORT_BYTES = 2 * 1024 * 1024
_MAX_TARGETS = 128
_MAX_WARMUPS = 100
_MAX_SAMPLES = 1000
_MAX_TIMING_US = 2**63 - 1
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ReportErrorKind = Literal[
    "report-missing",
    "io-error",
    "report-limit",
    "report-invalid",
    "report-unsupported",
    "context-invalid",
    "cohort-invalid",
    "cohort-mismatch",
]


class MeasurementReportError(ValueError):
    """A measurement artifact cannot be safely decoded or analyzed."""

    __slots__ = ("differing_fields", "kind", "reason", "source_index")

    def __init__(
        self,
        kind: _ReportErrorKind,
        reason: str,
        *,
        source_index: int | None = None,
        differing_fields: tuple[str, ...] = (),
    ) -> None:
        self.kind = kind
        self.reason = reason
        self.source_index = source_index
        self.differing_fields = tuple(sorted(differing_fields))
        super().__init__(reason)


def _timing(value: object, name: str) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_TIMING_US:
        raise ValueError(f"{name} must be a non-negative 64-bit integer")
    return value


def _timings(
    values: object, name: str, *, minimum: int, maximum: int
) -> tuple[int, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{name} must be an array of integer microseconds")
    if not minimum <= len(values) <= maximum:
        raise ValueError(f"{name} count is outside the supported range")
    return tuple(_timing(value, name) for value in values)


@dataclass(frozen=True, slots=True)
class ReportIdentity:
    """The four safe interpreter attributes actually present in a report."""

    implementation: str
    python: str
    platform: str
    machine: str

    def __post_init__(self) -> None:
        identity = EnvironmentIdentity(
            self.implementation, self.python, self.platform, self.machine
        )
        object.__setattr__(self, "machine", identity.machine)


@dataclass(frozen=True, slots=True)
class ReportTarget:
    """Ordered child observations for one target, without baseline policy."""

    warmups_us: tuple[int, ...]
    samples_us: tuple[int, ...]
    upper_median_us: int

    def __post_init__(self) -> None:
        warmups = _timings(self.warmups_us, "warmups_us", minimum=0, maximum=100)
        samples = _timings(self.samples_us, "samples_us", minimum=1, maximum=1000)
        median = _timing(self.upper_median_us, "upper_median_us")
        if sorted(samples)[len(samples) // 2] != median:
            raise ValueError("upper_median_us does not match recorded samples")
        object.__setattr__(self, "warmups_us", warmups)
        object.__setattr__(self, "samples_us", samples)


@dataclass(frozen=True, slots=True)
class MeasurementReport:
    """One complete immutable v1 observation with byte-level provenance."""

    environment: ReportIdentity
    sampling: SamplingPolicy
    targets: Mapping[str, ReportTarget]
    source_sha256: str
    report_version: int = 1

    def __post_init__(self) -> None:
        if type(self.report_version) is not int or self.report_version != 1:
            raise ValueError("report_version must be 1")
        if not isinstance(self.environment, ReportIdentity):
            raise ValueError("environment must be a ReportIdentity")
        if not isinstance(self.sampling, SamplingPolicy):
            raise ValueError("sampling must be a SamplingPolicy")
        if not 0 <= self.sampling.warmups <= _MAX_WARMUPS:
            raise ValueError("warmups count exceeds the report limit")
        if not 1 <= self.sampling.samples <= _MAX_SAMPLES:
            raise ValueError("samples count exceeds the report limit")
        if (
            not isinstance(self.targets, Mapping)
            or not 1 <= len(self.targets) <= _MAX_TARGETS
        ):
            raise ValueError("targets must contain 1 to 128 entries")
        for module, target in self.targets.items():
            _validate_module_name(module)
            if not isinstance(target, ReportTarget):
                raise ValueError("targets must contain ReportTarget values")
            if (
                len(target.warmups_us) != self.sampling.warmups
                or len(target.samples_us) != self.sampling.samples
            ):
                raise ValueError("target observations differ from sampling counts")
        if (
            not isinstance(self.source_sha256, str)
            or _DIGEST.fullmatch(self.source_sha256) is None
        ):
            raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
        object.__setattr__(
            self, "targets", MappingProxyType(dict(sorted(self.targets.items())))
        )


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("measurement report contains a duplicate JSON key")
        result[key] = value
    return result


def _reject_number(_value: str) -> None:
    raise ValueError("measurement report requires integer timing values")


def _exact_object(value: object, keys: set[str], section: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{section} has missing or unexpected fields")
    return cast(dict[str, Any], value)


def _decode(raw: bytes) -> MeasurementReport:
    source = raw.decode("utf-8")
    document = json.loads(
        source,
        object_pairs_hook=_unique_pairs,
        parse_float=_reject_number,
        parse_constant=_reject_number,
    )
    if not isinstance(document, dict):
        raise ValueError("measurement report must be a JSON object")
    if document.get("report_type") != "measurement":
        raise ValueError("report_type must be measurement")
    version = document.get("report_version")
    if type(version) is not int or version != 1:
        raise MeasurementReportError(
            "report-unsupported", "unsupported measurement report_version"
        )
    root = _exact_object(
        document,
        {"environment", "report_type", "report_version", "sampling", "targets"},
        "measurement report",
    )
    environment = _exact_object(
        root["environment"],
        {"implementation", "python", "platform", "machine"},
        "environment",
    )
    sampling = _exact_object(
        root["sampling"], {"warmups", "samples", "statistic"}, "sampling"
    )
    for name, maximum in (("warmups", _MAX_WARMUPS), ("samples", _MAX_SAMPLES)):
        value = sampling[name]
        if type(value) is int and value > maximum:
            raise MeasurementReportError(
                "report-limit", f"{name} count exceeds the report limit"
            )
    target_values = root["targets"]
    if not isinstance(target_values, dict):
        raise ValueError("targets must be a JSON object")
    if len(target_values) > _MAX_TARGETS:
        raise MeasurementReportError("report-limit", "targets count exceeds 128")
    for value in target_values.values():
        target = _exact_object(
            value, {"warmups_us", "samples_us", "upper_median_us"}, "target"
        )
        for name, maximum in (
            ("warmups_us", _MAX_WARMUPS),
            ("samples_us", _MAX_SAMPLES),
        ):
            values = target[name]
            if isinstance(values, list) and len(values) > maximum:
                raise MeasurementReportError(
                    "report-limit", f"{name} count exceeds the report limit"
                )
    targets = {
        module: ReportTarget(
            **_exact_object(
                value,
                {"warmups_us", "samples_us", "upper_median_us"},
                "target",
            )
        )
        for module, value in target_values.items()
    }
    return MeasurementReport(
        ReportIdentity(**environment),
        SamplingPolicy(**sampling),
        targets,
        hashlib.sha256(raw).hexdigest(),
    )


def decode_measurement_report(raw: bytes | str) -> MeasurementReport:
    """Decode a bounded v1 artifact without filesystem or subprocess access."""
    if isinstance(raw, str):
        if len(raw) > _MAX_REPORT_BYTES:
            raise MeasurementReportError(
                "report-limit", "measurement report exceeds 2 MiB"
            )
        try:
            payload = raw.encode("utf-8")
        except UnicodeError as error:
            raise MeasurementReportError(
                "report-invalid", "measurement report is not valid UTF-8"
            ) from error
    elif isinstance(raw, bytes):
        payload = raw
    else:
        raise MeasurementReportError(
            "report-invalid", "measurement report must be bytes or text"
        )
    if len(payload) > _MAX_REPORT_BYTES:
        raise MeasurementReportError("report-limit", "measurement report exceeds 2 MiB")
    try:
        return _decode(payload)
    except MeasurementReportError:
        raise
    except UnicodeError as error:
        raise MeasurementReportError(
            "report-invalid", "measurement report is not valid UTF-8"
        ) from error
    except (TypeError, ValueError, RecursionError) as error:
        raise MeasurementReportError(
            "report-invalid", "measurement report has invalid v1 content"
        ) from error


def load_measurement_report(path: str | os.PathLike[str]) -> MeasurementReport:
    """Read one regular non-symlink file with a bounded read, then decode it."""
    try:
        source = Path(path)
        original = source.lstat()
        if not stat.S_ISREG(original.st_mode):
            raise MeasurementReportError(
                "io-error", "measurement report must be a regular non-symlink file"
            )
        if original.st_size > _MAX_REPORT_BYTES:
            raise MeasurementReportError(
                "report-limit", "measurement report exceeds 2 MiB"
            )
        with source.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or (
                original.st_dev,
                original.st_ino,
            ) != (opened.st_dev, opened.st_ino):
                raise MeasurementReportError(
                    "io-error", "measurement report changed during open"
                )
            payload = stream.read(_MAX_REPORT_BYTES + 1)
    except FileNotFoundError as error:
        raise MeasurementReportError(
            "report-missing", "measurement report file not found"
        ) from error
    except MeasurementReportError:
        raise
    except (OSError, TypeError, ValueError) as error:
        raise MeasurementReportError(
            "io-error", "cannot read measurement report"
        ) from error
    return decode_measurement_report(payload)
