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

"""Deterministic report-analysis CLI presentation and fail-closed inputs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from importtime_check import MeasurementReportError
from importtime_check._cli import main


def _document(*, email: int = 10, json_median: int = 42) -> dict[str, Any]:
    return {
        "environment": {
            "implementation": "cpython",
            "python": "3.11",
            "platform": "linux",
            "machine": "x86_64",
        },
        "report_type": "measurement",
        "report_version": 1,
        "sampling": {"warmups": 1, "samples": 3, "statistic": "upper_median"},
        "targets": {
            "json": {
                "warmups_us": [json_median + 3],
                "samples_us": [json_median - 2, json_median, json_median + 2],
                "upper_median_us": json_median,
            },
            "email": {
                "warmups_us": [email + 3],
                "samples_us": [email - 2, email, email + 2],
                "upper_median_us": email,
            },
        },
    }


def _write(path: Path, document: dict[str, Any]) -> str:
    payload = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode()
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _arguments(first: Path, second: Path, *extra: str) -> list[str]:
    return [
        "report",
        "summarize",
        "--file",
        str(first),
        "--file",
        str(second),
        "--runner-context",
        "ubuntu24-py311",
        "--install-context",
        "build-before",
        *extra,
    ]


def _compare_arguments(
    before: Sequence[Path], after: Sequence[Path], *extra: str
) -> list[str]:
    return [
        "report",
        "compare",
        "--before-file",
        str(before[0]),
        "--before-file",
        str(before[1]),
        "--after-file",
        str(after[0]),
        "--after-file",
        str(after[1]),
        "--runner-context",
        "ubuntu24-py311",
        "--before-install-context",
        "build-before",
        "--after-install-context",
        "build-after",
        *extra,
    ]


def test_summary_text_and_json_are_complete_and_input_order_independent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first_digest = _write(first, _document(email=10, json_median=42))
    second_digest = _write(second, _document(email=11, json_median=41))
    assert main(_arguments(first, second)) == 0
    text = capsys.readouterr()
    assert text.err == ""
    assert text.out == (
        "Cohort: 2 reports; runner ubuntu24-py311; install build-before\n"
        "Environment: cpython 3.11, linux/x86_64\n"
        "Sampling: 1 warmup(s), 3 recorded sample(s), upper_median\n"
        "email: observed median 11 us; range 10..11 us; spread 1 us\n"
        "json: observed median 42 us; range 41..42 us; spread 1 us\n"
        "Descriptive only; no regression verdict.\n"
    )
    assert main(_arguments(first, second, "--format", "json")) == 0
    rendered = capsys.readouterr()
    assert rendered.err == ""
    assert rendered.out.endswith("\n")
    parsed = json.loads(rendered.out)
    assert rendered.out == json.dumps(parsed, sort_keys=True, indent=2) + "\n"
    assert parsed == {
        "analysis_type": "cohort_summary",
        "analysis_version": 1,
        "environment": {
            "implementation": "cpython",
            "python": "3.11",
            "platform": "linux",
            "machine": "x86_64",
        },
        "sampling": {"warmups": 1, "samples": 3, "statistic": "upper_median"},
        "runner_context": "ubuntu24-py311",
        "install_context": "build-before",
        "report_count": 2,
        "sources_sha256": sorted((first_digest, second_digest)),
        "targets": {
            "email": {
                "run_medians_us": [
                    median
                    for _, median in sorted(((first_digest, 10), (second_digest, 11)))
                ],
                "observed_median_us": 11,
                "min_us": 10,
                "max_us": 11,
                "spread_us": 1,
            },
            "json": {
                "run_medians_us": [
                    median
                    for _, median in sorted(((first_digest, 42), (second_digest, 41)))
                ],
                "observed_median_us": 42,
                "min_us": 41,
                "max_us": 42,
                "spread_us": 1,
            },
        },
    }
    assert main(_arguments(second, first, "--format", "json")) == 0
    assert capsys.readouterr().out == rendered.out


@pytest.mark.parametrize(
    ("second_kind", "expected"),
    [
        ("missing", "report-missing at report #2"),
        ("malformed", "report-invalid at report #2"),
        ("duplicate", "cohort-invalid at report #2"),
        ("mismatch", "cohort-mismatch at report #2 (environment.python)"),
    ],
)
def test_later_file_failure_has_safe_stderr_and_empty_stdout(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    second_kind: str,
    expected: str,
) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "private-name-second.json"
    _write(first, _document())
    if second_kind == "malformed":
        second.write_text("{secret-not-json", encoding="utf-8")
    elif second_kind == "duplicate":
        second.write_bytes(first.read_bytes())
    elif second_kind == "mismatch":
        document = _document(email=11)
        document["environment"]["python"] = "3.12"
        _write(second, document)
    assert main(_arguments(first, second, "--format", "json")) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == f"importtime-check: {expected}\n"
    assert "private-name" not in output.err
    assert "secret-not-json" not in output.err


def test_invalid_context_or_report_count_fails_without_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    _write(first, _document())
    _write(second, _document(email=11))
    invalid_context = _arguments(first, second)
    invalid_context[-1] = "bad/path"
    assert main(invalid_context) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "importtime-check: context-invalid\n"
    one = [
        "report",
        "summarize",
        "--file",
        str(first),
        "--runner-context",
        "runner",
        "--install-context",
        "install",
    ]
    assert main(one) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "importtime-check: cohort-invalid\n"
    many = one + ["--file", str(first)] * 64
    assert main(many) == 2
    assert capsys.readouterr().out == ""


def test_summary_help_and_debug_error_behavior(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as help_exit:
        main(["report", "summarize", "--help"])
    assert help_exit.value.code == 0
    help_output = capsys.readouterr()
    assert "--runner-context" in help_output.out
    assert "--install-context" in help_output.out
    assert "--file" in help_output.out
    with pytest.raises(SystemExit) as invalid_exit:
        main(["report", "summarize", "--file", "missing"])
    assert invalid_exit.value.code == 2
    assert capsys.readouterr().out == ""
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    _write(first, _document())
    with pytest.raises(MeasurementReportError) as failure:
        main(["--debug", *_arguments(first, second)])
    assert failure.value.kind == "report-missing"
    assert failure.value.source_index == 2


def test_comparison_text_and_json_are_deterministic_and_versioned(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = tuple(tmp_path / f"run-{index}.json" for index in range(4))
    digests = (
        _write(paths[0], _document(email=10, json_median=42)),
        _write(paths[1], _document(email=11, json_median=41)),
        _write(paths[2], _document(email=14, json_median=47)),
        _write(paths[3], _document(email=15, json_median=48)),
    )
    args = _compare_arguments(paths[:2], paths[2:])
    assert main(args) == 0
    text = capsys.readouterr()
    assert text.err == ""
    assert text.out == (
        "Comparison: before 2 reports (install build-before); "
        "after 2 reports (install build-after); runner ubuntu24-py311\n"
        "Environment: cpython 3.11, linux/x86_64\n"
        "Sampling: 1 warmup(s), 3 recorded sample(s), upper_median\n"
        "email: 11 -> 15 us (+4 us, +36.36%); "
        "before range 10..11 us (spread 1 us); "
        "after range 14..15 us (spread 1 us)\n"
        "json: 42 -> 48 us (+6 us, +14.29%); "
        "before range 41..42 us (spread 1 us); "
        "after range 47..48 us (spread 1 us)\n"
        "Descriptive only; no regression verdict.\n"
    )
    assert main([*args, "--format", "json"]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    document = json.loads(output.out)
    assert output.out == json.dumps(document, sort_keys=True, indent=2) + "\n"
    assert tuple(document) == (
        "after",
        "analysis_type",
        "analysis_version",
        "before",
        "changes",
    )
    assert document["analysis_type"] == "cohort_comparison"
    assert document["analysis_version"] == 1
    assert document["before"]["analysis_type"] == "cohort_summary"
    assert document["after"]["analysis_type"] == "cohort_summary"
    assert document["before"]["sources_sha256"] == sorted(digests[:2])
    assert document["after"]["sources_sha256"] == sorted(digests[2:])
    assert document["changes"] == {
        "email": {
            "before_us": 11,
            "after_us": 15,
            "change_us": 4,
            "change_percent": "+36.36",
        },
        "json": {
            "before_us": 42,
            "after_us": 48,
            "change_us": 6,
            "change_percent": "+14.29",
        },
    }
    shuffled = _compare_arguments(
        (paths[1], paths[0]), (paths[3], paths[2]), "--format", "json"
    )
    assert main(shuffled) == 0
    assert capsys.readouterr().out == output.out


def test_comparison_text_shows_zero_denominator_and_exact_zero_change(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = tuple(tmp_path / f"zero-{index}.json" for index in range(4))
    for index, (email, json_median) in enumerate(((0, 42), (0, 41), (1, 42), (2, 41))):
        document = _document(email=max(email, 2), json_median=json_median)
        document["targets"]["email"] = {
            "warmups_us": [email],
            "samples_us": [email, email, email],
            "upper_median_us": email,
        }
        _write(paths[index], document)
    assert main(_compare_arguments(paths[:2], paths[2:])) == 0
    rendered = capsys.readouterr().out
    assert "email: 0 -> 2 us (+2 us, n/a)" in rendered
    assert "json: 42 -> 42 us (0 us, 0.00%)" in rendered
    assert main(_compare_arguments(paths[:2], paths[2:], "--format", "json")) == 0
    changes = json.loads(capsys.readouterr().out)["changes"]
    assert changes["email"]["change_percent"] is None
    assert changes["json"]["change_us"] == 0


@pytest.mark.parametrize("side", ["before", "after"])
def test_later_comparison_file_error_is_side_specific_and_stdout_empty(
    side: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = tuple(tmp_path / f"private-run-{index}.json" for index in range(4))
    for index, path in enumerate(paths):
        _write(path, _document(email=10 + index))
    invalid_index = 1 if side == "before" else 3
    paths[invalid_index].write_text("{private-invalid-json", encoding="utf-8")
    assert main(_compare_arguments(paths[:2], paths[2:], "--format", "json")) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == f"importtime-check: report-invalid at {side} report #2\n"
    assert "private" not in output.err


def test_comparison_mismatch_and_bad_context_fail_without_partial_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = tuple(tmp_path / f"run-{index}.json" for index in range(4))
    for index, path in enumerate(paths):
        _write(path, _document(email=10 + index))
    after_mismatch = _document(email=13)
    after_mismatch["environment"]["python"] = "3.12"
    _write(paths[3], after_mismatch)
    assert main(_compare_arguments(paths[:2], paths[2:])) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == (
        "importtime-check: cohort-mismatch at after report #2 (environment.python)\n"
    )
    other_after = _document(email=12)
    other_after["environment"]["python"] = "3.12"
    _write(paths[2], other_after)
    assert main(_compare_arguments(paths[:2], paths[2:])) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "importtime-check: cohort-mismatch (environment.python)\n"
    args = _compare_arguments(paths[:2], paths[2:])
    args[args.index("--before-install-context") + 1] = "bad/path"
    assert main(args) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "importtime-check: context-invalid in before cohort\n"


def test_comparison_counts_help_and_debug_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as help_exit:
        main(["report", "compare", "--help"])
    assert help_exit.value.code == 0
    help_text = capsys.readouterr().out
    for flag in (
        "--before-file",
        "--after-file",
        "--runner-context",
        "--before-install-context",
        "--after-install-context",
    ):
        assert flag in help_text
    with pytest.raises(SystemExit) as missing_exit:
        main(["report", "compare", "--before-file", "missing"])
    assert missing_exit.value.code == 2
    assert capsys.readouterr().out == ""
    paths = tuple(tmp_path / f"run-{index}.json" for index in range(4))
    for index, path in enumerate(paths):
        _write(path, _document(email=10 + index))
    args = _compare_arguments(paths[:2], paths[2:])
    before_short = args.copy()
    del before_short[
        before_short.index("--before-file") : before_short.index("--before-file") + 2
    ]
    assert main(before_short) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "importtime-check: cohort-invalid in before cohort\n"
    after_short = args.copy()
    del after_short[
        after_short.index("--after-file") : after_short.index("--after-file") + 2
    ]
    assert main(after_short) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "importtime-check: cohort-invalid in after cohort\n"
    with pytest.raises(MeasurementReportError) as before_error:
        main(["--debug", *before_short])
    assert before_error.value.kind == "cohort-invalid"
    with pytest.raises(MeasurementReportError) as after_error:
        main(["--debug", *after_short])
    assert after_error.value.kind == "cohort-invalid"
