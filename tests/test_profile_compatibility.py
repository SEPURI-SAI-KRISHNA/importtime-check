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

"""Keep fixed profile artifacts readable and invalid artifacts rejected."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from importtime_check import (
    ImportProfileError,
    encode_import_profile,
    inspect_import_profile,
    load_import_profile,
)

FIXTURES = Path(__file__).parent / "fixtures"
EXPECTED_SHA256 = {
    "profile-v1.json": "988124a41bd81c9b3e24b90f97c8d2561b73d51e42c7e3dcd98a27798e899e06",
    "profile-v1-two-target.json": "e051f14bf49dffe90e9d1b7fb60447d9027acf8014cf65c0eae7b288086136da",
    "profile-v1-duplicate-key.json": "9fd1055a9608beaea70c7d8fdffc09a87842272e0612ee9fa1aaa3c324f35d8a",
    "profile-v1-invalid-event.json": "4eaddf80b5b43998debc7bb8be49b234c21be2c1713535431fbbb73f763ac5af",
    "profile-v2-unsupported.json": "f6624cb1c2ae5baa680a001b5deb2ccb9bfce393c6fa7020a23c26d4dfe15f04",
}


@pytest.mark.parametrize("name", EXPECTED_SHA256)
def test_archived_profile_bytes_are_unchanged(name: str) -> None:
    assert (
        hashlib.sha256((FIXTURES / name).read_bytes()).hexdigest()
        == (EXPECTED_SHA256[name])
    )


@pytest.mark.parametrize("name", ("profile-v1.json", "profile-v1-two-target.json"))
def test_archived_v1_profiles_load_with_exact_source_bytes(name: str) -> None:
    path = FIXTURES / name
    loaded = load_import_profile(path)
    assert loaded.profile_version == 1
    assert loaded.source_sha256 == EXPECTED_SHA256[name]
    assert encode_import_profile(loaded) == path.read_bytes()
    assert loaded.environment.implementation == "cpython"
    assert loaded.sampling.samples == 1
    assert all(
        target.runs[0].events[-1].module == module
        for module, target in loaded.targets.items()
    )

    selected = inspect_import_profile(
        loaded, target="json", phase="sample", run_number=1, limit=2
    )
    assert selected.source_sha256 == EXPECTED_SHA256[name]
    assert selected.event_count == 3
    assert [row.occurrence for row in selected.self_time] == [1, 2]
    assert [row.occurrence for row in selected.cumulative_time] == [3, 2]


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("profile-v1-duplicate-key.json", "invalid"),
        ("profile-v1-invalid-event.json", "invalid"),
        ("profile-v2-unsupported.json", "unsupported-version"),
    ],
)
def test_archived_invalid_profiles_fail_closed(name: str, kind: str) -> None:
    with pytest.raises(ImportProfileError) as failure:
        load_import_profile(FIXTURES / name)
    assert failure.value.kind == kind
    assert "profile" in failure.value.reason
