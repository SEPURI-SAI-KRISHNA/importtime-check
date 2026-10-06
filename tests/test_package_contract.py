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

"""Tests for the installed package and distribution metadata contract."""

from importlib import metadata

import importtime_check

DISTRIBUTION_NAME = "importtime-check"


def test_public_version_matches_distribution_metadata() -> None:
    """The public version and installed distribution version have one value."""
    assert importtime_check.__version__ == metadata.version(DISTRIBUTION_NAME)
    assert "__version__" in importtime_check.__all__


def test_distribution_metadata_preserves_packaging_contract() -> None:
    """Installed metadata keeps the Python, license, and dependency promises."""
    package_metadata = metadata.metadata(DISTRIBUTION_NAME)

    assert package_metadata["Requires-Python"] == ">=3.11"
    assert package_metadata["License-Expression"] == "Apache-2.0"
    assert package_metadata.get_all("Requires-Dist") == [
        "pytest>=9.1.1; extra == 'pytest'"
    ]
    assert package_metadata.get_all("Provides-Extra") == ["pytest"]
    assert not any(
        entry.group == "pytest11"
        for entry in metadata.distribution(DISTRIBUTION_NAME).entry_points
    )
