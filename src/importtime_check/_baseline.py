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

"""Schema-1 baseline values, canonical JSON, and explicit file I/O."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, cast

from ._measurement import _validate_module_name
from ._sampling import _count

_PERCENT = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
_PYTHON = re.compile(r"[0-9]+\.[0-9]+\Z")
_ErrorKind = Literal[
    "baseline-missing",
    "baseline-invalid",
    "schema-unsupported",
    "environment-mismatch",
    "target-set-mismatch",
    "interpreter-probe-failed",
    "io-error",
]


class BaselineError(ValueError):
    """A baseline or environment cannot be safely compared."""

    __slots__ = ("differing_fields", "kind", "missing", "reason", "stale")

    def __init__(
        self,
        kind: _ErrorKind,
        reason: str,
        *,
        missing: tuple[str, ...] = (),
        stale: tuple[str, ...] = (),
        differing_fields: tuple[str, ...] = (),
    ) -> None:
        self.kind = kind
        self.reason = reason
        self.missing = missing
        self.stale = stale
        self.differing_fields = tuple(differing_fields)
        super().__init__(reason)


def _nonnegative_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _percent(value: object) -> str:
    if not isinstance(value, str) or _PERCENT.fullmatch(value) is None:
        raise ValueError("max_increase_percent must be a non-negative decimal string")
    whole, separator, fraction = value.partition(".")
    fraction = fraction.rstrip("0")
    return whole + ("." + fraction if separator and fraction else "")


def _percent_ratio(value: str) -> tuple[int, int]:
    whole, _, fraction = value.partition(".")
    return int(whole + fraction), 10 ** len(fraction)


@dataclass(frozen=True, slots=True)
class EnvironmentIdentity:
    """Comparable attributes reported by the selected interpreter."""

    implementation: str
    python: str
    platform: str
    machine: str
    profile: str = "default"

    def __post_init__(self) -> None:
        if self.implementation != "cpython":
            raise ValueError("implementation must be cpython")
        if not isinstance(self.python, str) or _PYTHON.fullmatch(self.python) is None:
            raise ValueError("python must be a major.minor version")
        if not isinstance(self.platform, str) or not self.platform.strip():
            raise ValueError("platform must be non-blank")
        if not isinstance(self.machine, str) or not self.machine.strip():
            raise ValueError("machine must be non-blank")
        if not isinstance(self.profile, str) or not self.profile.strip():
            raise ValueError("profile must be non-blank")
        object.__setattr__(self, "machine", self.machine.strip().lower())


@dataclass(frozen=True, slots=True)
class SamplingPolicy:
    """Recorded sampling settings used for every baseline target."""

    warmups: int = 1
    samples: int = 5
    statistic: str = "upper_median"

    def __post_init__(self) -> None:
        _count(self.warmups, "warmups", 0)
        _count(self.samples, "samples", 1)
        if self.statistic != "upper_median":
            raise ValueError("statistic must be upper_median")


@dataclass(frozen=True, slots=True)
class TargetBaseline:
    """Approved median and absolute/relative increase allowances."""

    baseline_cumulative_us: int
    max_increase_us: int
    max_increase_percent: str

    def __post_init__(self) -> None:
        _nonnegative_int(self.baseline_cumulative_us, "baseline_cumulative_us")
        _nonnegative_int(self.max_increase_us, "max_increase_us")
        object.__setattr__(
            self, "max_increase_percent", _percent(self.max_increase_percent)
        )


@dataclass(frozen=True, slots=True)
class Baseline:
    """Immutable schema-1 baseline with a copied target mapping."""

    environment: EnvironmentIdentity
    sampling: SamplingPolicy
    targets: Mapping[str, TargetBaseline]
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("schema_version must be 1")
        if not isinstance(self.environment, EnvironmentIdentity):
            raise ValueError("environment must be an EnvironmentIdentity")
        if not isinstance(self.sampling, SamplingPolicy):
            raise ValueError("sampling must be a SamplingPolicy")
        if not isinstance(self.targets, Mapping) or not self.targets:
            raise ValueError("targets must be a non-empty mapping")
        for module, target in self.targets.items():
            _validate_module_name(module)
            if not isinstance(target, TargetBaseline):
                raise ValueError("targets must contain TargetBaseline values")
        object.__setattr__(
            self, "targets", MappingProxyType(dict(sorted(self.targets.items())))
        )


def _exact_object(value: object, keys: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{name} must contain exactly: {', '.join(sorted(keys))}")
    return cast(dict[str, Any], value)


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def decode_baseline(raw: bytes | str) -> Baseline:
    """Decode and validate a baseline without filesystem access."""
    try:
        source = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        document = json.loads(
            source, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant
        )
        if not isinstance(document, dict):
            raise ValueError("baseline must be a JSON object")
        version = document.get("schema_version")
        if type(version) is not int or version != 1:
            raise BaselineError(
                "schema-unsupported",
                f"unsupported baseline schema_version: {version!r}",
            )
        root = _exact_object(
            document,
            {"schema_version", "environment", "sampling", "targets"},
            "baseline",
        )
        environment = _exact_object(
            root["environment"],
            {"implementation", "python", "platform", "machine", "profile"},
            "environment",
        )
        sampling = _exact_object(
            root["sampling"], {"warmups", "samples", "statistic"}, "sampling"
        )
        target_values = root["targets"]
        if not isinstance(target_values, dict):
            raise ValueError("targets must be a JSON object")
        targets = {
            module: TargetBaseline(
                **_exact_object(
                    value,
                    {
                        "baseline_cumulative_us",
                        "max_increase_us",
                        "max_increase_percent",
                    },
                    f"target {module!r}",
                )
            )
            for module, value in target_values.items()
        }
        return Baseline(
            EnvironmentIdentity(**environment),
            SamplingPolicy(**sampling),
            targets,
        )
    except BaselineError:
        raise
    except (UnicodeError, TypeError, ValueError) as error:
        raise BaselineError("baseline-invalid", str(error)) from error


def encode_baseline(baseline: Baseline) -> bytes:
    """Return canonical, platform-independent schema-1 JSON bytes."""
    if not isinstance(baseline, Baseline):
        raise ValueError("baseline must be a Baseline")
    document = {
        "schema_version": baseline.schema_version,
        "environment": {
            "implementation": baseline.environment.implementation,
            "python": baseline.environment.python,
            "platform": baseline.environment.platform,
            "machine": baseline.environment.machine,
            "profile": baseline.environment.profile,
        },
        "sampling": {
            "warmups": baseline.sampling.warmups,
            "samples": baseline.sampling.samples,
            "statistic": baseline.sampling.statistic,
        },
        "targets": {
            module: {
                "baseline_cumulative_us": target.baseline_cumulative_us,
                "max_increase_us": target.max_increase_us,
                "max_increase_percent": target.max_increase_percent,
            }
            for module, target in baseline.targets.items()
        },
    }
    return (
        json.dumps(
            document, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2
        )
        + "\n"
    ).encode("utf-8")


def load_baseline(path: str | os.PathLike[str]) -> Baseline:
    """Read one explicit file and decode its baseline."""
    try:
        return decode_baseline(Path(path).read_bytes())
    except FileNotFoundError as error:
        raise BaselineError(
            "baseline-missing", f"baseline file not found: {path}"
        ) from error
    except OSError as error:
        raise BaselineError("io-error", f"cannot read baseline: {error}") from error


def save_baseline(
    path: str | os.PathLike[str], baseline: Baseline, *, replace: bool = False
) -> None:
    """Publish canonical bytes atomically, refusing implicit replacement."""
    destination = Path(path)
    payload = encode_baseline(baseline)
    try:
        with tempfile.TemporaryDirectory(
            prefix=".importtime-check-", dir=destination.parent
        ) as directory:
            temporary = Path(directory) / "baseline.json"
            with temporary.open("wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if replace:
                os.replace(temporary, destination)
            else:
                os.link(temporary, destination)
    except FileExistsError as error:
        raise BaselineError(
            "io-error", f"baseline already exists: {destination}"
        ) from error
    except OSError as error:
        raise BaselineError("io-error", f"cannot write baseline: {error}") from error
