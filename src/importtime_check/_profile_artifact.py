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

"""Canonical encoding and strict offline loading of version-1 import profiles."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any, cast

from ._baseline import SamplingPolicy
from ._measurement_report import ReportIdentity
from ._model import ImportTimeEvent
from ._profile import ImportProfile, ImportProfileError, ProfileRun, ProfileTarget

_MAX_PROFILE_BYTES = 8 * 1024 * 1024
_MAX_TARGETS = 16
_MAX_RUNS_PER_TARGET = 25
_MAX_EVENTS_PER_RUN = 5_000
_MAX_EVENTS_TOTAL = 50_000


def encode_import_profile(profile: ImportProfile) -> bytes:
    """Encode validated evidence as canonical UTF-8 JSON, without I/O."""
    if not isinstance(profile, ImportProfile):
        raise ImportProfileError("invalid", "profile must be an ImportProfile")
    document: dict[str, object] = {
        "profile_type": "import-profile",
        "profile_version": profile.profile_version,
        "environment": {
            "implementation": profile.environment.implementation,
            "python": profile.environment.python,
            "platform": profile.environment.platform,
            "machine": profile.environment.machine,
        },
        "sampling": {
            "warmups": profile.sampling.warmups,
            "samples": profile.sampling.samples,
            "statistic": profile.sampling.statistic,
        },
        "targets": {
            module: {
                "runs": [
                    {
                        "phase": run.phase,
                        "number": run.number,
                        "events": [
                            {
                                "module": event.module,
                                "self_us": event.self_us,
                                "cumulative_us": event.cumulative_us,
                                "depth": event.depth,
                            }
                            for event in run.events
                        ],
                    }
                    for run in target.runs
                ]
            }
            for module, target in profile.targets.items()
        },
    }
    payload = (
        json.dumps(document, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    if len(payload) > _MAX_PROFILE_BYTES:
        raise ImportProfileError("oversized", "import profile exceeds 8 MiB")
    return payload


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_number(_value: str) -> None:
    raise ValueError("profile requires integer event values")


def _exact_object(value: object, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("missing or unexpected profile fields")
    return cast(dict[str, Any], value)


def _decode(payload: bytes) -> ImportProfile:
    document = json.loads(
        payload.decode("utf-8"),
        object_pairs_hook=_unique_pairs,
        parse_float=_reject_number,
        parse_constant=_reject_number,
    )
    if (
        not isinstance(document, dict)
        or document.get("profile_type") != "import-profile"
    ):
        raise ValueError("not an import profile")
    version = document.get("profile_version")
    if type(version) is int and version != 1:
        raise ImportProfileError("unsupported-version", "unsupported profile_version")
    root = _exact_object(
        document,
        {"environment", "profile_type", "profile_version", "sampling", "targets"},
    )
    if type(version) is not int or version != 1:
        raise ValueError("invalid profile_version")
    environment = _exact_object(
        root["environment"], {"implementation", "python", "platform", "machine"}
    )
    sampling = _exact_object(root["sampling"], {"warmups", "samples", "statistic"})
    target_values = root["targets"]
    if not isinstance(target_values, dict):
        raise ValueError("targets must be an object")
    if len(target_values) > _MAX_TARGETS:
        raise ImportProfileError("oversized", "profile has too many targets")

    targets: dict[str, ProfileTarget] = {}
    total_events = 0
    for module, target_value in target_values.items():
        target = _exact_object(target_value, {"runs"})
        run_values = target["runs"]
        if not isinstance(run_values, list):
            raise ValueError("runs must be an array")
        if len(run_values) > _MAX_RUNS_PER_TARGET:
            raise ImportProfileError("oversized", "profile has too many runs")
        runs: list[ProfileRun] = []
        for run_value in run_values:
            run = _exact_object(run_value, {"phase", "number", "events"})
            event_values = run["events"]
            if not isinstance(event_values, list):
                raise ValueError("events must be an array")
            if len(event_values) > _MAX_EVENTS_PER_RUN:
                raise ImportProfileError("oversized", "profile has too many run events")
            total_events += len(event_values)
            if total_events > _MAX_EVENTS_TOTAL:
                raise ImportProfileError("oversized", "profile has too many events")
            events = tuple(
                ImportTimeEvent(
                    **_exact_object(
                        event_value,
                        {"module", "self_us", "cumulative_us", "depth"},
                    )
                )
                for event_value in event_values
            )
            runs.append(ProfileRun(run["phase"], run["number"], events))
        targets[module] = ProfileTarget(module, tuple(runs))
    return ImportProfile(
        ReportIdentity(**environment),
        SamplingPolicy(**sampling),
        targets,
        source_sha256=hashlib.sha256(payload).hexdigest(),
    )


def _decode_import_profile(payload: bytes) -> ImportProfile:
    """Decode one bounded byte stream without filesystem or child access."""
    if not isinstance(payload, bytes):
        raise ImportProfileError("invalid", "import profile must be bytes")
    if len(payload) > _MAX_PROFILE_BYTES:
        raise ImportProfileError("oversized", "import profile exceeds 8 MiB")
    try:
        return _decode(payload)
    except ImportProfileError:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise ImportProfileError(
            "invalid", "invalid import profile artifact"
        ) from error


def load_import_profile(path: str | os.PathLike[str]) -> ImportProfile:
    """Load one bounded regular non-symlink file with exact-byte provenance."""
    try:
        source = Path(path)
        original = source.lstat()
        if not stat.S_ISREG(original.st_mode):
            raise ImportProfileError("io", "profile must be a regular non-symlink file")
        if original.st_size > _MAX_PROFILE_BYTES:
            raise ImportProfileError("oversized", "import profile exceeds 8 MiB")
        with source.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if not stat.S_ISREG(opened.st_mode) or (
                original.st_dev,
                original.st_ino,
            ) != (opened.st_dev, opened.st_ino):
                raise ImportProfileError("io", "profile changed during open")
            payload = stream.read(_MAX_PROFILE_BYTES + 1)
    except ImportProfileError:
        raise
    except (OSError, TypeError, ValueError) as error:
        raise ImportProfileError("io", "cannot read import profile") from error
    return _decode_import_profile(payload)
