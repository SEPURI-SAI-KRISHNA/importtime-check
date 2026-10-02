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
import importtime_check

assert importtime_check.__version__ == metadata.version("importtime-check")
assert metadata.requires("importtime-check") is None
"""


class WheelSmokeError(RuntimeError):
    """The built wheel could not satisfy its clean-install contract."""


def _environment_python(environment: Path) -> Path:
    scripts_directory = "Scripts" if os.name == "nt" else "bin"
    executable = "python.exe" if os.name == "nt" else "python"
    return environment / scripts_directory / executable


def _run(command: Sequence[str], *, cwd: Path | None = None) -> None:
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
        )
    except subprocess.TimeoutExpired as error:
        raise WheelSmokeError("command timed out after 120 seconds") from error
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no output"
        raise WheelSmokeError(
            f"command failed with exit code {completed.returncode}: {detail}"
        )


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
