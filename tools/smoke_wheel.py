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

"""Install a built wheel offline and verify its isolated import contract."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import venv
from collections.abc import Sequence
from pathlib import Path

from tools.validate_artifacts import ArtifactValidationError, discover_artifacts

SMOKE_PROGRAM = """
from importlib import metadata
from importlib import util
from pathlib import Path
import sys
import importtime_check

assert Path(importtime_check.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
assert importtime_check.__version__ == metadata.version("importtime-check")
assert metadata.requires("importtime-check") == ["pytest>=9.1.1; extra == 'pytest'"]
assert util.find_spec("pytest") is None
assert "pytest" not in sys.modules
assert callable(importtime_check.refresh_baseline)
assert callable(importtime_check.decode_measurement_report)
assert callable(importtime_check.load_measurement_report)
assert any(
    entry.name == "importtime-check"
    and entry.value == "importtime_check._cli:main"
    for entry in metadata.distribution("importtime-check").entry_points
)
"""

REPORT_READER_PROGRAM = """
import json
from pathlib import Path
import sys
from importtime_check import (
    compare_report_cohorts,
    decode_measurement_report,
    load_measurement_report,
    summarize_measurement_reports,
)

path = Path(sys.argv[1])
loaded = load_measurement_report(path)
assert loaded == decode_measurement_report(path.read_bytes())
assert tuple(loaded.targets) == ("email", "json")
assert loaded.sampling.warmups == 0
assert loaded.sampling.samples == 1
second_document = json.loads(path.read_bytes())
second_target = second_document["targets"]["email"]
second_target["samples_us"][0] += 1
second_target["upper_median_us"] += 1
second = decode_measurement_report(json.dumps(second_document))
summary = summarize_measurement_reports(
    (second, loaded), runner_context="wheel-smoke", install_context="wheel-under-test"
)
assert summary.report_count == 2
assert tuple(summary.targets) == ("email", "json")
assert summary.targets["email"].spread_us == 1
assert summary.sources_sha256 == tuple(sorted((loaded.source_sha256, second.source_sha256)))
after_reports = []
for shift in (2, 3):
    document = json.loads(path.read_bytes())
    target = document["targets"]["email"]
    target["samples_us"][0] += shift
    target["upper_median_us"] += shift
    after_reports.append(decode_measurement_report(json.dumps(document)))
after = summarize_measurement_reports(
    after_reports, runner_context="wheel-smoke", install_context="wheel-after"
)
comparison = compare_report_cohorts(summary, after)
assert comparison.changes["email"].change_us == 2
assert comparison.before.targets["email"].spread_us == 1
assert comparison.after.targets["email"].spread_us == 1
assert not hasattr(comparison, "status")
"""


class WheelSmokeError(RuntimeError):
    """The built wheel could not satisfy its clean-install contract."""


def _clean_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    return environment


def _environment_python(environment: Path) -> Path:
    scripts_directory = "Scripts" if os.name == "nt" else "bin"
    executable = "python.exe" if os.name == "nt" else "python"
    return environment / scripts_directory / executable


def _environment_command(environment: Path) -> Path:
    scripts_directory = "Scripts" if os.name == "nt" else "bin"
    executable = "importtime-check.exe" if os.name == "nt" else "importtime-check"
    return environment / scripts_directory / executable


def _run(
    command: Sequence[str], *, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            env=_clean_environment(),
        )
    except subprocess.TimeoutExpired as error:
        raise WheelSmokeError("command timed out after 120 seconds") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no output"
        raise WheelSmokeError(
            f"command failed with exit code {completed.returncode}: {detail}"
        )
    return completed


def _expect_report_error(command: Sequence[str], *, cwd: Path, expected: str) -> None:
    """Require the installed command to reject bad reports without stdout."""
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            env=_clean_environment(),
        )
    except subprocess.TimeoutExpired as error:
        raise WheelSmokeError("rejected report command timed out") from error
    if (
        completed.returncode != 2
        or completed.stdout != ""
        or completed.stderr.strip() != expected
    ):
        raise WheelSmokeError("installed command did not safely reject a bad report")


def smoke_wheel(dist_dir: Path) -> Path:
    """Install the only wheel in *dist_dir* without an index or dependencies."""
    try:
        wheel, _ = discover_artifacts(dist_dir.resolve())
    except ArtifactValidationError as error:
        raise WheelSmokeError(str(error)) from error

    with tempfile.TemporaryDirectory(prefix="importtime-check-wheel-") as temporary:
        temporary_path = Path(temporary)
        environment = temporary_path / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = _environment_python(environment)
        _run(
            (
                str(python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--no-deps",
                str(wheel),
            )
        )
        _run((str(python), "-I", "-c", SMOKE_PROGRAM), cwd=temporary_path)
        command_path = _environment_command(environment)
        if not command_path.is_file():
            raise WheelSmokeError("installed console command is missing")
        command: tuple[str, ...] = (str(command_path),)
        try:
            _run((*command, "--help"), cwd=temporary_path)
        except OSError as error:
            if os.name != "nt" or getattr(error, "winerror", None) != 4551:
                raise
            # Application Control can block pip's launcher in temporary
            # directories. Verify its metadata and file, then exercise the
            # installed target through the clean wheel interpreter.
            command = (
                str(python),
                "-I",
                "-c",
                "from importtime_check._cli import main; raise SystemExit(main())",
            )
            _run((*command, "--help"), cwd=temporary_path)
        _run(
            (
                *command,
                "measure",
                "--module",
                "json",
                "--warmups",
                "0",
                "--samples",
                "1",
            ),
            cwd=temporary_path,
        )
        measured = _run(
            (
                *command,
                "measure",
                "--module",
                "json",
                "--module",
                "email",
                "--warmups",
                "0",
                "--samples",
                "1",
                "--format",
                "json",
            ),
            cwd=temporary_path,
        )
        try:
            report = json.loads(measured.stdout)
            if (
                not isinstance(report, dict)
                or report.get("report_type") != "measurement"
                or report.get("report_version") != 1
                or not isinstance(report.get("targets"), dict)
                or tuple(report["targets"]) != ("email", "json")
                or any(
                    target.get("warmups_us") != []
                    or not isinstance(target.get("samples_us"), list)
                    or len(target["samples_us"]) != 1
                    or target.get("upper_median_us") != target["samples_us"][0]
                    for target in report["targets"].values()
                )
            ):
                raise ValueError("unexpected measurement report")
        except (AttributeError, TypeError, ValueError) as error:
            raise WheelSmokeError("invalid two-target measurement JSON") from error
        report_file = temporary_path / "measurement.json"
        report_file.write_bytes(measured.stdout.encode("utf-8"))
        _run(
            (str(python), "-I", "-c", REPORT_READER_PROGRAM, str(report_file)),
            cwd=temporary_path,
        )
        second_report = temporary_path / "measurement-second.json"
        second_document = json.loads(measured.stdout)
        second_target = second_document["targets"]["email"]
        second_target["samples_us"][0] += 1
        second_target["upper_median_us"] += 1
        second_report.write_text(json.dumps(second_document), encoding="utf-8")
        summarized = _run(
            (
                *command,
                "report",
                "summarize",
                "--file",
                str(report_file),
                "--file",
                str(second_report),
                "--runner-context",
                "wheel-smoke",
                "--install-context",
                "wheel-under-test",
                "--format",
                "json",
            ),
            cwd=temporary_path,
        )
        try:
            cohort = json.loads(summarized.stdout)
            if (
                cohort.get("analysis_type") != "cohort_summary"
                or cohort.get("analysis_version") != 1
                or cohort.get("report_count") != 2
                or tuple(cohort.get("targets", {})) != ("email", "json")
                or cohort["targets"]["email"]["spread_us"] != 1
            ):
                raise ValueError("unexpected cohort summary")
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise WheelSmokeError("invalid cohort summary JSON") from error
        after_files: list[Path] = []
        for shift in (2, 3):
            after_document = json.loads(measured.stdout)
            after_target = after_document["targets"]["email"]
            after_target["samples_us"][0] += shift
            after_target["upper_median_us"] += shift
            after_file = temporary_path / f"measurement-after-{shift}.json"
            after_file.write_text(json.dumps(after_document), encoding="utf-8")
            after_files.append(after_file)
        compared = _run(
            (
                *command,
                "report",
                "compare",
                "--before-file",
                str(report_file),
                "--before-file",
                str(second_report),
                "--after-file",
                str(after_files[0]),
                "--after-file",
                str(after_files[1]),
                "--runner-context",
                "wheel-smoke",
                "--before-install-context",
                "wheel-under-test",
                "--after-install-context",
                "wheel-after",
                "--format",
                "json",
            ),
            cwd=temporary_path,
        )
        try:
            comparison = json.loads(compared.stdout)
            if (
                comparison.get("analysis_type") != "cohort_comparison"
                or comparison.get("analysis_version") != 1
                or comparison["before"]["report_count"] != 2
                or comparison["after"]["report_count"] != 2
                or comparison["changes"]["email"]["change_us"] != 2
            ):
                raise ValueError("unexpected cohort comparison")
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise WheelSmokeError("invalid cohort comparison JSON") from error
        malformed = temporary_path / "malformed.json"
        malformed.write_text(
            '{"report_type":"measurement","report_version":1,"report_version":1}',
            encoding="utf-8",
        )
        _expect_report_error(
            (
                *command,
                "report",
                "summarize",
                "--file",
                str(report_file),
                "--file",
                str(malformed),
                "--runner-context",
                "wheel-smoke",
                "--install-context",
                "wheel-under-test",
                "--format",
                "json",
            ),
            cwd=temporary_path,
            expected="importtime-check: report-invalid at report #2",
        )
        future = temporary_path / "future.json"
        future.write_text(
            '{"report_type":"measurement","report_version":2}',
            encoding="utf-8",
        )
        _expect_report_error(
            (
                *command,
                "report",
                "compare",
                "--before-file",
                str(report_file),
                "--before-file",
                str(second_report),
                "--after-file",
                str(after_files[0]),
                "--after-file",
                str(future),
                "--runner-context",
                "wheel-smoke",
                "--before-install-context",
                "wheel-under-test",
                "--after-install-context",
                "wheel-after",
                "--format",
                "json",
            ),
            cwd=temporary_path,
            expected="importtime-check: report-unsupported at after report #2",
        )
        baseline = temporary_path / "baseline.json"
        _run(
            (
                *command,
                "baseline",
                "record",
                "--output",
                str(baseline),
                "--module",
                "json",
                "--max-increase-us",
                "100000000000000000000",
                "--max-increase-percent",
                "0",
                "--warmups",
                "0",
                "--samples",
                "1",
            ),
            cwd=temporary_path,
        )
        _run(
            (
                *command,
                "baseline",
                "refresh",
                "--file",
                str(baseline),
                "--replace",
            ),
            cwd=temporary_path,
        )
        _run(
            (*command, "check", "--baseline", str(baseline), "--format", "json"),
            cwd=temporary_path,
        )
    return wheel


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dist_dir", type=Path, help="directory containing one wheel and sdist"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the wheel smoke test and return a process exit status."""
    arguments = _parser().parse_args(argv)
    try:
        wheel = smoke_wheel(arguments.dist_dir)
    except (OSError, WheelSmokeError) as error:
        print(f"wheel smoke test failed: {error}", file=sys.stderr)
        return 1
    print(f"wheel smoke test passed: {wheel.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
