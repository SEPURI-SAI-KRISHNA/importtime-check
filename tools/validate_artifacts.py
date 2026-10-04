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

"""Validate built wheel and source-distribution contracts."""

from __future__ import annotations

import argparse
import ast
import sys
import tarfile
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from email.message import Message
from email.parser import BytesParser
from email.policy import compat32
from pathlib import Path, PurePosixPath
from typing import cast

DIST_NAME = "importtime-check"
NORMALIZED_NAME = "importtime_check"
IMPORT_NAME = "importtime_check"
EXPECTED_LICENSE_FILES = frozenset({"LICENSE", "NOTICE"})
EXPECTED_PACKAGE_FILES = (
    "__init__.py",
    "_baseline.py",
    "_cli.py",
    "_measurement.py",
    "_model.py",
    "_parser.py",
    "_regression.py",
    "_report.py",
    "_sampling.py",
    "_version.py",
    "py.typed",
)
EXPECTED_SDIST_FILES = (
    "CONTRIBUTING.md",
    "docs/design/0001-packaging-and-compatibility.md",
    "docs/design/0002-quality-and-test-policy.md",
    "docs/design/0003-contribution-governance-and-release-tracking.md",
    "docs/design/0004-contributor-friendly-templates.md",
    "docs/design/0005-parser-and-domain-model-contract.md",
    "docs/design/0006-isolated-measurement-and-sampling.md",
    "docs/design/0007-regression-and-integration-contract.md",
    "docs/design/README.md",
    "LICENSE",
    "NOTICE",
    "README.md",
    "SECURITY.md",
    "pyproject.toml",
    "src/importtime_check/__init__.py",
    "src/importtime_check/_baseline.py",
    "src/importtime_check/_cli.py",
    "src/importtime_check/_measurement.py",
    "src/importtime_check/_model.py",
    "src/importtime_check/_parser.py",
    "src/importtime_check/_regression.py",
    "src/importtime_check/_report.py",
    "src/importtime_check/_sampling.py",
    "src/importtime_check/_version.py",
    "src/importtime_check/py.typed",
    "tests/test_artifact_validation.py",
    "tests/test_baseline.py",
    "tests/test_cli.py",
    "tests/test_measurement.py",
    "tests/test_package_contract.py",
    "tests/test_parser.py",
    "tests/test_regression.py",
    "tests/test_report.py",
    "tests/test_sampling.py",
    "tools/__init__.py",
    "tools/smoke_wheel.py",
    "tools/validate_artifacts.py",
)


class ArtifactValidationError(ValueError):
    """A built distribution violates the repository packaging contract."""


@dataclass(frozen=True, slots=True)
class ArtifactSet:
    """The one wheel and one source distribution produced by a build."""

    wheel: Path
    sdist: Path
    version: str


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ArtifactValidationError(message)


def _metadata_value(metadata: Message, field: str, source: str) -> str:
    value = metadata[field]
    _require(value is not None, f"{source} is missing {field}")
    return str(value)


def _metadata_values(metadata: Message, field: str) -> tuple[str, ...]:
    return tuple(str(value) for value in metadata.get_all(field, []))


def _validate_metadata(raw: bytes, source: str, expected_version: str) -> None:
    metadata = BytesParser(policy=compat32).parsebytes(raw)
    _require(
        _metadata_value(metadata, "Name", source) == DIST_NAME, f"Bad Name in {source}"
    )
    _require(
        _metadata_value(metadata, "Version", source) == expected_version,
        f"Bad Version in {source}",
    )
    _require(
        _metadata_value(metadata, "Requires-Python", source) == ">=3.11",
        f"Bad Requires-Python in {source}",
    )
    _require(
        _metadata_value(metadata, "License-Expression", source) == "Apache-2.0",
        f"Bad License-Expression in {source}",
    )
    _require(
        frozenset(_metadata_values(metadata, "License-File")) == EXPECTED_LICENSE_FILES,
        f"Bad License-File values in {source}",
    )
    _require(
        not _metadata_values(metadata, "Requires-Dist"),
        f"Runtime dependency found in {source}",
    )
    _require(
        not _metadata_values(metadata, "Provides-Extra"),
        f"Published extra found in {source}",
    )
    header_names = {name.casefold() for name in metadata}
    _require(
        "dependency-group" not in header_names
        and "dependency-groups" not in header_names,
        f"Development dependency groups leaked into {source}",
    )


def _source_version(project_root: Path) -> str:
    version_path = project_root / "src" / IMPORT_NAME / "_version.py"
    try:
        tree = ast.parse(
            version_path.read_text(encoding="utf-8"), filename=str(version_path)
        )
    except (OSError, SyntaxError) as error:
        raise ArtifactValidationError(f"Cannot read version source: {error}") from error

    values: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name) and target.id == "__version__":
            value = ast.literal_eval(node.value)
            _require(isinstance(value, str), "__version__ must be a string literal")
            values.append(value)

    _require(len(values) == 1, "Version source must define one __version__ literal")
    return values[0]


def _validate_dependency_groups(raw: bytes, source: str) -> None:
    try:
        import tomllib

        document = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ArtifactValidationError(f"Cannot parse {source}: {error}") from error

    groups_object = document.get("dependency-groups")
    _require(isinstance(groups_object, dict), f"{source} has no dependency groups")
    groups = cast(dict[str, object], groups_object)
    _require(
        set(groups) == {"test", "quality", "packaging", "dev"},
        f"{source} has unexpected dependency groups",
    )
    _require(
        groups["dev"]
        == [
            {"include-group": "test"},
            {"include-group": "quality"},
            {"include-group": "packaging"},
        ],
        f"{source} does not compose the dev group",
    )

    project_object = document.get("project")
    _require(isinstance(project_object, dict), f"{source} has no project table")
    project = cast(dict[str, object], project_object)
    _require(project.get("dependencies") == [], f"{source} has runtime dependencies")
    _require(
        "optional-dependencies" not in project,
        f"{source} publishes development tools as extras",
    )


def discover_artifacts(dist_dir: Path) -> tuple[Path, Path]:
    """Return the single wheel and sdist in *dist_dir*."""
    _require(dist_dir.is_dir(), f"Artifact directory does not exist: {dist_dir}")
    artifacts = sorted(path for path in dist_dir.iterdir() if path.is_file())
    wheels = [path for path in artifacts if path.suffix == ".whl"]
    sdists = [path for path in artifacts if path.name.endswith(".tar.gz")]
    _require(
        len(artifacts) == 2, f"Expected exactly two artifacts, found {len(artifacts)}"
    )
    _require(len(wheels) == 1, f"Expected exactly one wheel, found {len(wheels)}")
    _require(len(sdists) == 1, f"Expected exactly one sdist, found {len(sdists)}")
    return wheels[0], sdists[0]


def _validate_wheel(path: Path, project_root: Path, version: str) -> None:
    expected_name = f"{NORMALIZED_NAME}-{version}-py3-none-any.whl"
    _require(path.name == expected_name, f"Unexpected wheel filename: {path.name}")
    dist_info = f"{NORMALIZED_NAME}-{version}.dist-info"

    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            for filename in EXPECTED_PACKAGE_FILES:
                archive_name = f"{IMPORT_NAME}/{filename}"
                _require(archive_name in names, f"Wheel is missing {archive_name}")
                source = project_root / "src" / IMPORT_NAME / filename
                _require(
                    archive.read(archive_name) == source.read_bytes(),
                    f"Wheel contains stale {archive_name}",
                )

            _require(
                not any(name.startswith(("tests/", "tools/")) for name in names),
                "Wheel contains repository-only tests or tools",
            )
            for license_name in EXPECTED_LICENSE_FILES:
                _require(
                    f"{dist_info}/licenses/{license_name}" in names,
                    f"Wheel is missing {license_name}",
                )
            _validate_metadata(
                archive.read(f"{dist_info}/METADATA"),
                "wheel METADATA",
                version,
            )
    except (KeyError, OSError, zipfile.BadZipFile) as error:
        raise ArtifactValidationError(
            f"Cannot inspect wheel {path.name}: {error}"
        ) from error


def _validate_sdist(path: Path, project_root: Path, version: str) -> None:
    expected_name = f"{NORMALIZED_NAME}-{version}.tar.gz"
    _require(path.name == expected_name, f"Unexpected sdist filename: {path.name}")
    prefix = PurePosixPath(f"{NORMALIZED_NAME}-{version}")

    try:
        with tarfile.open(path, mode="r:gz") as archive:
            names = set(archive.getnames())
            for relative_name in EXPECTED_SDIST_FILES:
                archive_name = str(prefix / relative_name)
                _require(archive_name in names, f"Sdist is missing {relative_name}")
                member = archive.extractfile(archive_name)
                if member is None:
                    raise ArtifactValidationError(
                        f"Cannot read {relative_name} from sdist"
                    )
                raw = member.read()
                source = project_root / relative_name
                _require(
                    raw == source.read_bytes(), f"Sdist contains stale {relative_name}"
                )
                if relative_name == "pyproject.toml":
                    _validate_dependency_groups(raw, "sdist pyproject.toml")

            pkg_info_name = str(prefix / "PKG-INFO")
            _require(pkg_info_name in names, "Sdist is missing PKG-INFO")
            pkg_info = archive.extractfile(pkg_info_name)
            if pkg_info is None:
                raise ArtifactValidationError("Cannot read sdist PKG-INFO")
            _validate_metadata(pkg_info.read(), "sdist PKG-INFO", version)
    except (KeyError, OSError, tarfile.TarError) as error:
        raise ArtifactValidationError(
            f"Cannot inspect sdist {path.name}: {error}"
        ) from error


def validate_artifacts(dist_dir: Path, project_root: Path) -> ArtifactSet:
    """Validate fresh artifacts against the current project sources."""
    resolved_root = project_root.resolve()
    version = _source_version(resolved_root)
    wheel, sdist = discover_artifacts(dist_dir.resolve())
    _validate_wheel(wheel, resolved_root, version)
    _validate_sdist(sdist, resolved_root, version)
    return ArtifactSet(wheel=wheel, sdist=sdist, version=version)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dist_dir", type=Path, help="directory containing one wheel and sdist"
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="source checkout used to build the artifacts (default: current directory)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run artifact validation and return a process exit status."""
    arguments = _parser().parse_args(argv)
    try:
        artifacts = validate_artifacts(arguments.dist_dir, arguments.project_root)
    except ArtifactValidationError as error:
        print(f"artifact validation failed: {error}", file=sys.stderr)
        return 1

    print(
        "artifact validation passed: "
        f"{artifacts.wheel.name}, {artifacts.sdist.name} ({artifacts.version})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
