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

"""Read-only CLI inspection, stable output, and safe failure boundaries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from importtime_check import ImportProfileError
from importtime_check._cli import main

_FIXTURE = Path(__file__).parent / "fixtures" / "profile-v1-two-target.json"


def _command(*extra: str, file: Path = _FIXTURE) -> list[str]:
    return [
        "profile",
        "show",
        "--file",
        str(file),
        "--target",
        "email",
        "--phase",
        "sample",
        "--run",
        "1",
        *extra,
    ]


def test_text_and_json_show_exact_evidence(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(_command("--limit", "2")) == 0
    text = capsys.readouterr()
    assert text.err == ""
    assert 'Target: "email"; sample 1; events: 3; shown per ranking: 2' in text.out
    assert "Cumulative time (us; overlapping, not additive):" in text.out
    assert text.out.count("email.utils") == 3

    assert main(_command("--limit", "2", "--format", "json")) == 0
    rendered = capsys.readouterr()
    assert rendered.err == ""
    document = json.loads(rendered.out)
    assert document["inspection_type"] == "import-profile-run"
    assert document["target"] == "email"
    assert [row["occurrence"] for row in document["rankings"]["self_time"]["rows"]] == [
        1,
        2,
    ]
    assert [
        row["occurrence"] for row in document["rankings"]["cumulative_time"]["rows"]
    ] == [3, 2]


@pytest.mark.parametrize(
    ("args", "category"),
    [
        (("--run", "2"), "invalid"),
        (("--target", "missing"), "invalid"),
        (("--limit", "0"), "invalid"),
        (("--limit", "101"), "invalid"),
    ],
    ids=("absent-run", "absent-target", "zero-limit", "large-limit"),
)
def test_expected_selection_errors_use_code_two_empty_stdout(
    args: tuple[str, ...], category: str, capsys: pytest.CaptureFixture[str]
) -> None:
    command = _command("--format", "json")
    option = args[0]
    if option in command:
        command[command.index(option) + 1] = args[1]
    else:
        command.extend(args)
    assert main(command) == 2
    result = capsys.readouterr()
    assert result.out == ""
    assert result.err.startswith(f"importtime-check: profile {category}:")
    assert str(_FIXTURE) not in result.err


def test_bad_file_is_safe_and_debug_reraises(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "private-profile.json"
    bad.write_text("{", encoding="utf-8")
    assert main(_command(file=bad)) == 2
    result = capsys.readouterr()
    assert result.out == ""
    assert result.err.startswith("importtime-check: profile invalid:")
    assert str(bad) not in result.err
    with pytest.raises(ImportProfileError):
        main(["--debug", *_command(file=bad)])
    capsys.readouterr()


def test_argparse_syntax_errors_keep_standard_usage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as invalid:
        main(["profile", "show", "--file", str(_FIXTURE)])
    assert invalid.value.code == 2
    result = capsys.readouterr()
    assert result.out == ""
    assert "usage:" in result.err
