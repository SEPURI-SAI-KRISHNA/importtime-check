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

"""Explicit, fail-closed candidate creation through the installed CLI route."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest

import importtime_check._cli as cli
from importtime_check import (
    Baseline,
    BaselineError,
    EnvironmentIdentity,
    SamplingPolicy,
    TargetBaseline,
    decode_baseline,
    encode_baseline,
    save_baseline,
)


def _document(*, email: int = 10, json_us: int = 40) -> dict[str, Any]:
    return {
        "environment": {
            "implementation": "cpython",
            "python": "3.11",
            "platform": "linux",
            "machine": "x86_64",
        },
        "report_type": "measurement",
        "report_version": 1,
        "sampling": {"warmups": 0, "samples": 1, "statistic": "upper_median"},
        "targets": {
            name: {
                "warmups_us": [],
                "samples_us": [value],
                "upper_median_us": value,
            }
            for name, value in (("email", email), ("json", json_us))
        },
    }


def _write(path: Path, document: dict[str, Any]) -> None:
    path.write_text(json.dumps(document), encoding="utf-8")


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    output = tmp_path / "candidate.json"
    _write(first, _document(email=10, json_us=40))
    _write(second, _document(email=11, json_us=41))
    return first, second, output


def _args(first: Path, second: Path, output: Path, *extra: str) -> list[str]:
    return [
        "baseline",
        "propose",
        "--file",
        str(first),
        "--file",
        str(second),
        "--runner-context",
        "ci-runner",
        "--install-context",
        "wheel-under-test",
        "--profile",
        "ci-reviewed",
        "--budget",
        "email=5,2.50",
        "--budget",
        "json=0,0",
        "--output",
        str(output),
        *extra,
    ]


def test_two_target_candidate_is_canonical_and_requires_review(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first, second, output = _inputs(tmp_path)
    assert cli.main(_args(first, second, output)) == 0
    result = capsys.readouterr()
    assert result.err == ""
    assert result.out == (
        "Created unapproved candidate for 2 target(s).\n"
        "Review its evidence and budgets in a separate approval PR before CI use.\n"
    )
    candidate = decode_baseline(output.read_bytes())
    assert output.read_bytes() == encode_baseline(candidate)
    assert candidate.environment.profile == "ci-reviewed"
    assert tuple(candidate.targets) == ("email", "json")
    assert candidate.targets["email"] == TargetBaseline(11, 5, "2.5")
    assert candidate.targets["json"] == TargetBaseline(41, 0, "0")
    assert cli.main(_args(second, first, tmp_path / "reverse.json")) == 0
    assert (tmp_path / "reverse.json").read_bytes() == output.read_bytes()


def test_explain_prints_review_evidence_without_private_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first, second, output = _inputs(tmp_path)
    assert cli.main(_args(first, second, output, "--explain")) == 0
    rendered = capsys.readouterr()
    assert rendered.err == ""
    assert rendered.out.startswith("Unapproved baseline candidate;")
    assert (
        f"Candidate SHA-256: {hashlib.sha256(output.read_bytes()).hexdigest()}"
        in rendered.out
    )
    assert "Source reports: 2" in rendered.out
    assert "Runner context: ci-runner" in rendered.out
    assert "Install context: wheel-under-test" in rendered.out
    assert "profile ci-reviewed" in rendered.out
    assert "candidate median 11 us; allowances 5 us or 2.5%" in rendered.out
    assert "candidate median 41 us; allowances 0 us or 0%" in rendered.out
    assert str(tmp_path) not in rendered.out
    assert "Changed policy fields:" not in rendered.out
    raw = output.read_bytes()
    assert b"Source reports" not in raw and b"ci-runner" not in raw
    output.unlink()
    assert cli.main(_args(second, first, output, "--explain")) == 0
    assert capsys.readouterr().out == rendered.out
    output.unlink()
    unsafe_profile = _args(first, second, output, "--explain")
    unsafe_profile[unsafe_profile.index("--profile") + 1] = "C:/private/profile"
    assert cli.main(unsafe_profile) == 0
    redacted = capsys.readouterr()
    assert "profile [redacted]" in redacted.out
    assert "C:/private/profile" not in redacted.out


def test_optional_comparison_names_fields_without_writing_old_policy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first, second, output = _inputs(tmp_path)
    approved = tmp_path / "approved.json"
    save_baseline(
        approved,
        Baseline(
            EnvironmentIdentity("cpython", "3.12", "linux", "x86_64", "old"),
            SamplingPolicy(0, 1),
            {"email": TargetBaseline(7, 1, "1")},
        ),
    )
    old_bytes = approved.read_bytes()
    assert (
        cli.main(_args(first, second, output, "--compare-baseline", str(approved))) == 0
    )
    rendered = capsys.readouterr()
    assert rendered.err == ""
    assert "Changed policy fields:" in rendered.out
    assert "  environment.python\n" in rendered.out
    assert "  environment.profile\n" in rendered.out
    assert "  targets.added.json\n" in rendered.out
    assert "  targets.email.baseline_cumulative_us\n" in rendered.out
    assert str(approved) not in rendered.out
    assert approved.read_bytes() == old_bytes
    assert decode_baseline(output.read_bytes()).targets["email"] == TargetBaseline(
        11, 5, "2.5"
    )
    assert output.read_bytes() == encode_baseline(decode_baseline(output.read_bytes()))


@pytest.mark.parametrize("invalid", ("missing", "invalid", "future"))
def test_invalid_comparison_policy_leaves_no_candidate_and_no_path_leak(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], invalid: str
) -> None:
    first, second, output = _inputs(tmp_path)
    previous = tmp_path / "private-approved.json"
    if invalid == "invalid":
        previous.write_text("{secret-token", encoding="utf-8")
    elif invalid == "future":
        previous.write_text('{"schema_version":2}', encoding="utf-8")
    assert (
        cli.main(_args(first, second, output, "--compare-baseline", str(previous))) == 2
    )
    result = capsys.readouterr()
    assert result.out == ""
    assert result.err.startswith("importtime-check: ")
    assert "comparison baseline was not loaded" in result.err
    assert str(previous) not in result.err
    assert "secret-token" not in result.err
    assert not output.exists()
    with pytest.raises(BaselineError):
        cli.main(
            [
                "--debug",
                *_args(first, second, output, "--compare-baseline", str(previous)),
            ]
        )


def test_explanation_is_not_printed_if_candidate_cannot_be_saved(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first, second, output = _inputs(tmp_path)
    output.write_bytes(b"old candidate")
    assert cli.main(_args(first, second, output, "--explain")) == 2
    result = capsys.readouterr()
    assert result.out == ""
    assert result.err == "importtime-check: io-error; candidate was not created\n"
    assert output.read_bytes() == b"old candidate"


@pytest.mark.parametrize(
    ("budgets", "expected"),
    [
        (("email=5,2", "email=6,3"), "proposal-invalid"),
        (("email=5,2", "json=5,2", "extra=0,0"), "unknown: extra"),
        (("email=5,2",), "missing: json"),
        (("json=5,2",), "missing: email"),
        (("email=5,2", "json=5,2", "other=0,0"), "unknown: other"),
        (("email=5,2", "other=0,0"), "missing: json; unknown: other"),
        (("email=-1,2", "json=5,2"), "proposal-invalid"),
        (("email=5,nan", "json=5,2"), "proposal-invalid"),
        (("private/path", "json=5,2"), "proposal-invalid"),
    ],
)
def test_invalid_budget_sets_cannot_create_candidates(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    budgets: tuple[str, ...],
    expected: str,
) -> None:
    first, second, output = _inputs(tmp_path)
    args = _args(first, second, output)
    budget_start = args.index("--budget")
    args = args[:budget_start]
    for budget in budgets:
        args.extend(("--budget", budget))
    args.extend(("--output", str(output)))
    assert cli.main(args) == 2
    result = capsys.readouterr()
    assert result.out == ""
    assert expected in result.err
    assert "private/path" not in result.err
    assert not output.exists()


@pytest.mark.parametrize(
    "failure", ("missing", "malformed", "future", "mismatch", "duplicate")
)
def test_bad_later_report_leaves_no_candidate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], failure: str
) -> None:
    first, second, output = _inputs(tmp_path)
    if failure == "missing":
        second.unlink()
    elif failure == "malformed":
        second.write_text("{secret-data", encoding="utf-8")
    elif failure == "future":
        document = _document(email=11, json_us=41)
        document["report_version"] = 2
        _write(second, document)
    elif failure == "mismatch":
        document = _document(email=11, json_us=41)
        document["environment"]["python"] = "3.12"
        _write(second, document)
    else:
        second.write_bytes(first.read_bytes())
    assert cli.main(_args(first, second, output)) == 2
    result = capsys.readouterr()
    assert result.out == ""
    assert "at report #2" in result.err
    assert str(second) not in result.err
    assert "secret-data" not in result.err
    assert not output.exists()


@pytest.mark.parametrize("kind", ("file", "directory", "symlink"))
def test_existing_destination_is_never_overwritten(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    first, second, output = _inputs(tmp_path)
    original = tmp_path / "approved.json"
    original.write_bytes(b"reviewed policy")
    if kind == "file":
        output.write_bytes(b"existing candidate")
    elif kind == "directory":
        output.mkdir()
    else:
        try:
            os.symlink(original, output)
        except OSError:
            pytest.skip("symlink creation is unavailable")
    assert cli.main(_args(first, second, output)) == 2
    result = capsys.readouterr()
    assert result.out == ""
    assert result.err == "importtime-check: io-error; candidate was not created\n"
    assert original.read_bytes() == b"reviewed policy"
    if kind == "file":
        assert output.read_bytes() == b"existing candidate"
    elif kind == "directory":
        assert output.is_dir()
    else:
        assert output.is_symlink()


def test_invalid_profile_and_context_do_not_write(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first, second, output = _inputs(tmp_path)
    args = _args(first, second, output)
    args[args.index("--profile") + 1] = " "
    assert cli.main(args) == 2
    assert capsys.readouterr().err == "importtime-check: proposal-invalid\n"
    assert not output.exists()
    args = _args(first, second, output)
    args[args.index("--runner-context") + 1] = "private/path"
    assert cli.main(args) == 2
    assert capsys.readouterr().err == "importtime-check: context-invalid\n"
    assert not output.exists()


def test_debug_and_interruption_preserve_fail_closed_behavior(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second, output = _inputs(tmp_path)
    args = _args(first, second, output)
    malformed = args.copy()
    malformed[malformed.index("--budget") + 1] = "wrong"
    with pytest.raises(ValueError, match="invalid or duplicate"):
        cli.main(["--debug", *malformed])
    output.write_bytes(b"existing")
    with pytest.raises(BaselineError):
        cli.main(["--debug", *args])
    assert output.read_bytes() == b"existing"
    output.unlink()

    def interrupted(*args: Any, **kwargs: Any) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "save_baseline", interrupted)
    with pytest.raises(KeyboardInterrupt):
        cli.main(_args(first, second, output))
    assert capsys.readouterr().out == ""
    assert not output.exists()


def test_parser_requires_only_explicit_proposal_options(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first, second, output = _inputs(tmp_path)
    args = _args(first, second, output)
    for option in (
        "--file",
        "--runner-context",
        "--install-context",
        "--profile",
        "--budget",
        "--output",
    ):
        without = args.copy()
        index = without.index(option)
        del without[index : index + 2]
        if option in ("--file", "--budget"):
            index = without.index(option)
            del without[index : index + 2]
        with pytest.raises(SystemExit) as error:
            cli.main(without)
        assert error.value.code == 2
        capsys.readouterr()
    for forbidden in (
        "--replace",
        "--max-increase-us",
        "--max-increase-percent",
        "--module",
    ):
        with pytest.raises(SystemExit) as error:
            cli.main([*args, forbidden, "1"])
        assert error.value.code == 2
        capsys.readouterr()
    assert not output.exists()
