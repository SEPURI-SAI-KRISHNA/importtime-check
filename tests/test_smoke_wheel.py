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

"""The installed-wheel smoke gate must fail on broken commands."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tools.smoke_wheel import WheelSmokeError, _expect_report_error, _run


def test_nonzero_installed_command_fails_smoke(tmp_path: Path) -> None:
    with pytest.raises(WheelSmokeError, match="exit code 2"):
        _run((sys.executable, "-c", "raise SystemExit(2)"), cwd=tmp_path)


def test_bad_report_must_fail_with_exact_safe_diagnostic(tmp_path: Path) -> None:
    accepted = (sys.executable, "-c", "print('unexpected success')")
    with pytest.raises(WheelSmokeError, match="did not safely reject"):
        _expect_report_error(accepted, cwd=tmp_path, expected="report-invalid")

    rejected = (
        sys.executable,
        "-c",
        "import sys; print('importtime-check: report-invalid at report #2', file=sys.stderr); raise SystemExit(2)",
    )
    _expect_report_error(
        rejected,
        cwd=tmp_path,
        expected="importtime-check: report-invalid at report #2",
    )
