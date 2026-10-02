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

"""Tests for maintained wheel and source-distribution validation."""

import io
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

import pytest

from tools.validate_artifacts import (
    EXPECTED_SDIST_FILES,
    ArtifactValidationError,
    discover_artifacts,
    main,
    validate_artifacts,
)

VERSION = "0.1.0a1"
STEM = f"importtime_check-{VERSION}"


def _metadata(*, runtime_dependency: bool = False) -> bytes:
    fields = [
        "Metadata-Version: 2.4",
        "Name: importtime-check",
        f"Version: {VERSION}",
        "Requires-Python: >=3.11",
        "License-Expression: Apache-2.0",
        "License-File: LICENSE",
        "License-File: NOTICE",
    ]
    if runtime_dependency:
        fields.append("Requires-Dist: example")
    fields.extend(("", "fixture description", ""))
    return "\n".join(fields).encode()


def _pyproject() -> bytes:
    return b"""
[project]
name = "importtime-check"
dependencies = []

[dependency-groups]
test = ["pytest"]
quality = ["ruff"]
packaging = ["build"]
dev = [
    { include-group = "test" },
    { include-group = "quality" },
    { include-group = "packaging" },
]
""".lstrip()


def _project_files() -> dict[str, bytes]:
    files = {name: f"fixture: {name}\n".encode() for name in EXPECTED_SDIST_FILES}
    files["pyproject.toml"] = _pyproject()
    files["src/importtime_check/__init__.py"] = b"from ._version import __version__\n"
    files["src/importtime_check/_version.py"] = f'__version__ = "{VERSION}"\n'.encode()
    files["src/importtime_check/py.typed"] = b""
    return files


def _write_project(root: Path, files: dict[str, bytes]) -> None:
    for relative_name, content in files.items():
        destination = root / relative_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)


def _add_tar_bytes(archive: tarfile.TarFile, name: str, content: bytes) -> None:
    member = tarfile.TarInfo(name=name)
    member.size = len(content)
    archive.addfile(member, io.BytesIO(content))


def _build_fixture_artifacts(
    project_root: Path,
    dist_dir: Path,
    *,
    wheel_runtime_dependency: bool = False,
    omitted_sdist_file: str | None = None,
) -> None:
    files = _project_files()
    _write_project(project_root, files)
    dist_dir.mkdir()

    wheel_path = dist_dir / f"{STEM}-py3-none-any.whl"
    dist_info = f"{STEM}.dist-info"
    with zipfile.ZipFile(wheel_path, mode="w") as archive:
        for filename in ("__init__.py", "_version.py", "py.typed"):
            source_name = f"src/importtime_check/{filename}"
            archive.writestr(f"importtime_check/{filename}", files[source_name])
        archive.writestr(f"{dist_info}/licenses/LICENSE", files["LICENSE"])
        archive.writestr(f"{dist_info}/licenses/NOTICE", files["NOTICE"])
        archive.writestr(
            f"{dist_info}/METADATA",
            _metadata(runtime_dependency=wheel_runtime_dependency),
        )

    sdist_path = dist_dir / f"{STEM}.tar.gz"
    prefix = PurePosixPath(STEM)
    with tarfile.open(sdist_path, mode="w:gz") as archive:
        for relative_name, content in files.items():
            if relative_name != omitted_sdist_file:
                _add_tar_bytes(archive, str(prefix / relative_name), content)
        _add_tar_bytes(archive, str(prefix / "PKG-INFO"), _metadata())


def test_validate_artifacts_accepts_matching_wheel_and_sdist(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    dist_dir = tmp_path / "dist"
    _build_fixture_artifacts(project_root, dist_dir)

    artifacts = validate_artifacts(dist_dir, project_root)

    assert artifacts.version == VERSION
    assert artifacts.wheel.name == f"{STEM}-py3-none-any.whl"
    assert artifacts.sdist.name == f"{STEM}.tar.gz"


def test_validate_artifacts_rejects_runtime_dependency(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    dist_dir = tmp_path / "dist"
    _build_fixture_artifacts(
        project_root,
        dist_dir,
        wheel_runtime_dependency=True,
    )

    with pytest.raises(ArtifactValidationError, match="Runtime dependency"):
        validate_artifacts(dist_dir, project_root)


def test_validate_artifacts_rejects_missing_sdist_file(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    dist_dir = tmp_path / "dist"
    _build_fixture_artifacts(
        project_root,
        dist_dir,
        omitted_sdist_file="tools/smoke_wheel.py",
    )

    with pytest.raises(ArtifactValidationError, match="Sdist is missing"):
        validate_artifacts(dist_dir, project_root)


def test_discover_artifacts_rejects_unexpected_file(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    dist_dir = tmp_path / "dist"
    _build_fixture_artifacts(project_root, dist_dir)
    (dist_dir / "unexpected.txt").write_text("unexpected", encoding="utf-8")

    with pytest.raises(ArtifactValidationError, match="exactly two"):
        discover_artifacts(dist_dir)


def test_main_returns_failure_for_missing_artifact_directory(tmp_path: Path) -> None:
    assert main((str(tmp_path / "missing"), "--project-root", str(tmp_path))) == 1
