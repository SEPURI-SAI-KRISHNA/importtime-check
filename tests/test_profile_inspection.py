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

"""Occurrence-preserving, bounded interpretation of selected profile runs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, cast

import pytest

from importtime_check import (
    ImportProfile,
    ImportProfileError,
    ImportTimeEvent,
    ProfileRun,
    ProfileTarget,
    ReportIdentity,
    SamplingPolicy,
    inspect_import_profile,
    load_import_profile,
)
from importtime_check._profile_report import (
    profile_inspection_json,
    profile_inspection_text,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "profile-v1-two-target.json"
_SHA256 = "e051f14bf49dffe90e9d1b7fb60447d9027acf8014cf65c0eae7b288086136da"


def test_fixed_two_target_rankings_keep_ties_repeats_and_source() -> None:
    assert hashlib.sha256(_FIXTURE.read_bytes()).hexdigest() == _SHA256
    profile = load_import_profile(_FIXTURE)
    assert tuple(profile.targets) == ("email", "json")
    inspection = inspect_import_profile(
        profile, target="email", phase="sample", run_number=1
    )
    assert inspection.source_sha256 == _SHA256
    assert inspection.target == "email"
    assert inspection.event_count == 3
    assert inspection.limit == 20
    assert [
        (row.occurrence, row.module, row.self_us) for row in inspection.self_time
    ] == [
        (1, "email.utils", 6),
        (2, "email.utils", 6),
        (3, "email", 0),
    ]
    assert [
        (row.occurrence, row.cumulative_us) for row in inspection.cumulative_time
    ] == [
        (3, 25),
        (2, 9),
        (1, 8),
    ]
    assert inspection.self_time[0] is inspection.cumulative_time[2]
    with pytest.raises(FrozenInstanceError):
        inspection.target = "json"  # type: ignore[misc]

    json_inspection = inspect_import_profile(
        profile, target="json", phase="sample", run_number=1, limit=2
    )
    assert json_inspection.target == "json"
    assert [row.occurrence for row in json_inspection.self_time] == [1, 2]
    assert [row.occurrence for row in json_inspection.cumulative_time] == [3, 2]
    assert json_inspection.event_count == 3


def test_json_and_text_label_exact_selected_evidence() -> None:
    inspection = inspect_import_profile(
        load_import_profile(_FIXTURE),
        target="email",
        phase="sample",
        run_number=1,
        limit=2,
    )
    raw = profile_inspection_json(inspection)
    document = json.loads(raw)
    assert raw.endswith("\n")
    assert document["inspection_type"] == "import-profile-run"
    assert document["source_sha256"] == _SHA256
    assert document["environment"] == {
        "implementation": "cpython",
        "machine": "x86_64",
        "platform": "linux",
        "python": "3.11",
    }
    assert (document["target"], document["phase"], document["run_number"]) == (
        "email",
        "sample",
        1,
    )
    assert document["rankings"]["self_time"]["metric"] == "self_us"
    assert [row["occurrence"] for row in document["rankings"]["self_time"]["rows"]] == [
        1,
        2,
    ]
    assert document["rankings"]["cumulative_time"]["metric"] == "cumulative_us"
    assert document["rankings"]["cumulative_time"]["overlapping_not_additive"] is True
    assert [
        row["occurrence"] for row in document["rankings"]["cumulative_time"]["rows"]
    ] == [3, 2]
    assert profile_inspection_json(inspection) == raw

    text = profile_inspection_text(inspection)
    assert f"Profile source SHA-256: {_SHA256}" in text
    assert 'Target: "email"; sample 1; events: 3; shown per ranking: 2' in text
    assert "Self time (us):" in text
    assert "Cumulative time (us; overlapping, not additive):" in text
    assert '  #1 6 us; cumulative 8 us; depth 1; module "email.utils"' in text
    assert '  #3 25 us; self 0 us; depth 0; module "email"' in text
    assert "42 us" not in text


def test_in_memory_warmup_is_selected_without_invented_digest() -> None:
    events = (ImportTimeEvent("json", 0, 0, 0),)
    profile = ImportProfile(
        ReportIdentity("cpython", "3.11", "linux", "x86_64"),
        SamplingPolicy(warmups=1, samples=1),
        {
            "json": ProfileTarget(
                "json",
                (ProfileRun("warmup", 1, events), ProfileRun("sample", 1, events)),
            )
        },
    )
    inspection = inspect_import_profile(
        profile, target="json", phase="warmup", run_number=1, limit=1
    )
    assert inspection.source_sha256 is None
    assert inspection.phase == "warmup"
    assert inspection.self_time[0].self_us == 0
    assert json.loads(profile_inspection_json(inspection))["source_sha256"] is None
    assert "none (in-memory capture)" in profile_inspection_text(inspection)


@pytest.mark.parametrize(
    ("target", "phase", "run_number", "limit"),
    [
        ("missing", "sample", 1, 20),
        (cast(Any, []), "sample", 1, 20),
        ("json", "other", 1, 20),
        ("json", "sample", 0, 20),
        ("json", "sample", True, 20),
        ("json", "sample", 1, 0),
        ("json", "sample", 1, 101),
        ("json", "sample", 1, True),
        ("json", "sample", 2, 20),
        ("json", "warmup", 1, 20),
    ],
)
def test_bad_selection_and_bounds_fail_without_partial_ranking(
    target: Any, phase: Any, run_number: Any, limit: Any
) -> None:
    with pytest.raises(ImportProfileError) as error:
        inspect_import_profile(
            load_import_profile(_FIXTURE),
            target=target,
            phase=phase,
            run_number=run_number,
            limit=limit,
        )
    assert error.value.kind == "invalid"
    assert "private" not in str(error.value)


def test_wrong_profile_type_and_limit_100() -> None:
    with pytest.raises(ImportProfileError) as wrong:
        inspect_import_profile(
            cast(Any, object()), target="json", phase="sample", run_number=1
        )
    assert wrong.value.kind == "invalid"
    selected = inspect_import_profile(
        load_import_profile(_FIXTURE),
        target="json",
        phase="sample",
        run_number=1,
        limit=100,
    )
    assert len(selected.self_time) == len(selected.cumulative_time) == 3
