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

"""Deterministic report-summary CLI presentation and fail-closed inputs."""

from __future__ import annotations

import hashlib
import json
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
