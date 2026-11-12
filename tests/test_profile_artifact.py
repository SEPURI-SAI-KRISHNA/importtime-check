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

"""Fixed-byte profile compatibility and strict offline artifact boundaries."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from importtime_check import (
    ImportProfileError,
    decode_baseline,
    decode_measurement_report,
    encode_baseline,
    encode_import_profile,
    load_import_profile,
)
from importtime_check import _profile_artifact as artifact

_FIXTURES = Path(__file__).parent / "fixtures"
_PROFILE = _FIXTURES / "profile-v1.json"
_BASELINE = _FIXTURES / "baseline-schema1.json"
_PROFILE_SHA256 = "988124a41bd81c9b3e24b90f97c8d2561b73d51e42c7e3dcd98a27798e899e06"
_BASELINE_SHA256 = "48e58ec79ca4e02d9ae687e7eadd163133072d2d3e354e86e7cef50fe4122ed0"


def _document() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(_PROFILE.read_bytes()))


def _payload(document: object) -> bytes:
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


def _events(document: dict[str, Any]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], document["targets"]["json"]["runs"][0]["events"])


def test_archived_profile_canonical_bytes_order_and_exact_digest(
    tmp_path: Path,
) -> None:
    raw = _PROFILE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == _PROFILE_SHA256
    loaded = load_import_profile(_PROFILE)
    assert loaded.source_sha256 == _PROFILE_SHA256
    assert loaded.profile_version == 1
    assert tuple(loaded.targets) == ("json",)
    assert [
        (event.module, event.self_us) for event in loaded.targets["json"].runs[0].events
    ] == [
        ("json.decoder", 6),
        ("json.decoder", 6),
        ("json", 2),
    ]
    assert encode_import_profile(loaded) == raw

    noncanonical = json.dumps(_document(), separators=(",", ":")).encode()
    path = tmp_path / "noncanonical.json"
    path.write_bytes(noncanonical)
    second = load_import_profile(path)
    assert second.source_sha256 == hashlib.sha256(noncanonical).hexdigest()
    assert second.source_sha256 != loaded.source_sha256
    assert encode_import_profile(second) == raw


def test_encoder_does_not_serialize_digest_or_read_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = load_import_profile(_PROFILE)

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("encoding cannot open files or launch children")

    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    assert encode_import_profile(loaded).startswith(b'{\n  "environment":')


def test_encoding_rejects_wrong_type_and_oversized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ImportProfileError) as wrong:
        encode_import_profile(cast(Any, object()))
    assert wrong.value.kind == "invalid"
    loaded = load_import_profile(_PROFILE)
    monkeypatch.setattr(artifact, "_MAX_PROFILE_BYTES", 1)
    with pytest.raises(ImportProfileError) as oversized:
        encode_import_profile(loaded)
    assert oversized.value.kind == "oversized"


@pytest.mark.parametrize(
    ("mutation", "kind"),
    [
        (lambda d: d.update(profile_type="measurement"), "invalid"),
        (lambda d: d.update(profile_version=2), "unsupported-version"),
        (lambda d: d.update(profile_version=True), "invalid"),
        (lambda d: d.update(extra=1), "invalid"),
        (lambda d: d.pop("sampling"), "invalid"),
        (lambda d: d.update(environment=[]), "invalid"),
        (lambda d: d["environment"].update(path="private"), "invalid"),
        (lambda d: d["environment"].update(implementation="pypy"), "invalid"),
        (lambda d: d.update(sampling=[]), "invalid"),
        (lambda d: d["sampling"].update(statistic="mean"), "invalid"),
        (lambda d: d.update(targets=[]), "invalid"),
        (lambda d: d.update(targets={}), "invalid"),
        (lambda d: d["targets"]["json"].update(stderr="private"), "invalid"),
        (lambda d: d["targets"]["json"].update(runs={}), "invalid"),
        (lambda d: d["targets"]["json"].update(runs=[]), "invalid"),
        (lambda d: d["targets"]["json"]["runs"][0].update(extra=1), "invalid"),
        (lambda d: d["targets"]["json"]["runs"][0].update(events={}), "invalid"),
        (lambda d: _events(d)[0].update(stderr="private"), "invalid"),
        (lambda d: _events(d)[0].update(module="not a module"), "invalid"),
        (lambda d: _events(d)[0].update(cumulative_us=1), "invalid"),
        (lambda d: d["targets"]["json"]["runs"][0].update(number=2), "invalid"),
        (lambda d: d["targets"]["json"]["runs"][0].update(phase="warmup"), "invalid"),
        (
            lambda d: d.update(
                targets={f"m{i}": d["targets"]["json"] for i in range(17)}
            ),
            "oversized",
        ),
        (
            lambda d: d["targets"]["json"].update(
                runs=[d["targets"]["json"]["runs"][0]] * 26
            ),
            "oversized",
        ),
        (
            lambda d: d["targets"]["json"]["runs"][0].update(events=_events(d) * 1667),
            "oversized",
        ),
    ],
    ids=[f"schema-{number}" for number in range(25)],
)
def test_invalid_schema_and_nested_limits(mutation: Any, kind: str) -> None:
    document = _document()
    mutation(document)
    with pytest.raises(ImportProfileError) as invalid:
        artifact._decode_import_profile(_payload(document))
    assert invalid.value.kind == kind


def test_total_event_limit_fails_before_materializing_excess() -> None:
    document = _document()
    event = {"module": "json.decoder", "self_us": 1, "cumulative_us": 1, "depth": 1}
    target = {"module": "json", "self_us": 1, "cumulative_us": 1, "depth": 0}
    runs = [
        {"phase": "sample", "number": number, "events": [event] * 4_999 + [target]}
        for number in range(1, 12)
    ]
    document["sampling"]["samples"] = 11
    document["targets"]["json"]["runs"] = runs
    with pytest.raises(ImportProfileError) as invalid:
        artifact._decode_import_profile(_payload(document))
    assert invalid.value.kind == "oversized"


@pytest.mark.parametrize(
    "raw",
    [
        b"{",
        b"[]",
        b"\xff",
        b'{"profile_type":"import-profile","profile_type":"import-profile"}',
        b'{"profile_type":"import-profile","profile_version":NaN}',
        b'{"profile_type":"import-profile","profile_version":1.0}',
    ],
)
def test_malformed_json_is_invalid(raw: bytes) -> None:
    with pytest.raises(ImportProfileError) as invalid:
        artifact._decode_import_profile(raw)
    assert invalid.value.kind == "invalid"


def test_decoder_rejects_wrong_input_type_and_byte_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ImportProfileError) as wrong:
        artifact._decode_import_profile(cast(Any, "{}"))
    assert wrong.value.kind == "invalid"
    monkeypatch.setattr(artifact, "_MAX_PROFILE_BYTES", 1)
    with pytest.raises(ImportProfileError) as too_large:
        artifact._decode_import_profile(b"{}")
    assert too_large.value.kind == "oversized"


def test_future_and_wrong_artifact_types_do_not_reinterpret_legacy_files(
    tmp_path: Path,
) -> None:
    baseline_raw = _BASELINE.read_bytes()
    assert hashlib.sha256(baseline_raw).hexdigest() == _BASELINE_SHA256
    assert encode_baseline(decode_baseline(baseline_raw)) == baseline_raw
    report_raw = (_FIXTURES / "report-v1-before-1.json").read_bytes()
    assert decode_measurement_report(report_raw).report_version == 1
    for name, raw in (("baseline", baseline_raw), ("report", report_raw)):
        path = tmp_path / f"{name}.json"
        path.write_bytes(raw)
        with pytest.raises(ImportProfileError) as wrong:
            load_import_profile(path)
        assert wrong.value.kind == "invalid"
    document = _document()
    document["profile_version"] = 2
    path = tmp_path / "future.json"
    path.write_bytes(_payload(document))
    with pytest.raises(ImportProfileError) as future:
        load_import_profile(path)
    assert future.value.kind == "unsupported-version"


def test_loader_missing_directory_bad_path_and_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ImportProfileError) as missing:
        load_import_profile(tmp_path / "missing.json")
    assert missing.value.kind == "io"
    with pytest.raises(ImportProfileError) as directory:
        load_import_profile(tmp_path)
    assert directory.value.kind == "io"
    with pytest.raises(ImportProfileError) as bad_path:
        load_import_profile(cast(Any, object()))
    assert bad_path.value.kind == "io"
    monkeypatch.setattr(artifact, "_MAX_PROFILE_BYTES", 1)
    with pytest.raises(ImportProfileError) as size:
        load_import_profile(_PROFILE)
    assert size.value.kind == "oversized"


def test_loader_rejects_changed_inode_and_read_overflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "profile.json"
    path.write_bytes(_PROFILE.read_bytes())
    real_fstat = os.fstat

    def changed(fd: int) -> SimpleNamespace:
        info = real_fstat(fd)
        return SimpleNamespace(
            st_mode=stat.S_IFREG, st_dev=info.st_dev, st_ino=info.st_ino + 1
        )

    monkeypatch.setattr(os, "fstat", changed)
    with pytest.raises(ImportProfileError) as changed_file:
        load_import_profile(path)
    assert changed_file.value.kind == "io"
    monkeypatch.setattr(os, "fstat", real_fstat)

    real_lstat = Path.lstat

    def understated(source: Path) -> SimpleNamespace:
        info = real_lstat(source)
        return SimpleNamespace(
            st_mode=info.st_mode,
            st_size=0,
            st_dev=info.st_dev,
            st_ino=info.st_ino,
        )

    monkeypatch.setattr(Path, "lstat", understated)
    monkeypatch.setattr(artifact, "_MAX_PROFILE_BYTES", 1)
    with pytest.raises(ImportProfileError) as read_overflow:
        load_import_profile(path)
    assert read_overflow.value.kind == "oversized"


def test_loader_rejects_symlink_when_supported(tmp_path: Path) -> None:
    link = tmp_path / "profile-link.json"
    try:
        link.symlink_to(_PROFILE)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(ImportProfileError) as linked:
        load_import_profile(link)
    assert linked.value.kind == "io"
