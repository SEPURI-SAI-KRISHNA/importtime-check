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

"""Guard the consuming-project proposal example and approved CI boundary."""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import cast

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "docs" / "examples"
APPROVED_BASELINE = "ci/importtime-baseline.json"
CANDIDATE = ".tmp/importtime-baseline-candidate.json"
EXPLANATION = ".tmp/importtime-baseline-review.txt"


def _workflow(name: str) -> dict[str, object]:
    """Load YAML 1.2-like strings; PyYAML's default treats `on` as a boolean."""
    yaml = importlib.import_module("yaml")
    document = yaml.load(
        (EXAMPLES / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader
    )
    assert isinstance(document, dict)
    return cast(dict[str, object], document)


def _steps(workflow: dict[str, object], job: str) -> list[dict[str, object]]:
    jobs = cast(dict[str, object], workflow["jobs"])
    definition = cast(dict[str, object], jobs[job])
    return cast(list[dict[str, object]], definition["steps"])


def _run_steps(steps: list[dict[str, object]]) -> str:
    return "\n".join(cast(str, step["run"]) for step in steps if "run" in step)


def _unsafe_candidate_workflow(workflow: dict[str, object]) -> bool:
    """Reject automatic triggers, write access, and direct policy promotion."""
    triggers = cast(dict[str, object], workflow["on"])
    permissions = cast(dict[str, str], workflow["permissions"])
    job = cast(dict[str, object], cast(dict[str, object], workflow["jobs"])["propose"])
    steps = _steps(workflow, "propose")
    commands = _run_steps(steps)
    return (
        set(triggers) != {"workflow_dispatch"}
        or permissions != {"contents": "read"}
        or "permissions" in job
        or any(
            cast(dict[str, str], step.get("with", {})).get("persist-credentials")
            != "false"
            for step in steps
            if str(step.get("uses", "")).startswith("actions/checkout@")
        )
        or APPROVED_BASELINE in commands
        or bool(
            re.search(r"\b(?:git\s+(?:add|commit|push)|gh\s+pr\s+create)\b", commands)
        )
        or "baseline refresh" in commands
        or "baseline record" in commands
        or "importtime-check check" in commands
    )


def test_example_workflows_are_valid_yaml() -> None:
    for name in (
        "check-importtime.yml",
        "collect-importtime-measurement.yml",
        "propose-importtime-baseline.yml",
        "record-importtime-baseline.yml",
    ):
        workflow = _workflow(name)
        assert isinstance(workflow["on"], dict)
        assert isinstance(workflow["jobs"], dict)


def test_proposal_workflow_is_manual_read_only_and_pinned() -> None:
    workflow = _workflow("propose-importtime-baseline.yml")
    assert not _unsafe_candidate_workflow(workflow)
    assert set(cast(dict[str, object], workflow["jobs"])) == {"propose"}
    steps = _steps(workflow, "propose")
    for step in steps:
        if "uses" in step:
            assert re.fullmatch(r"[\w-]+/[\w-]+@[0-9a-f]{40}", cast(str, step["uses"]))
    assert sum("actions/checkout@" in str(step.get("uses", "")) for step in steps) == 1
    assert (
        sum("actions/upload-artifact@" in str(step.get("uses", "")) for step in steps)
        == 1
    )
    job = cast(dict[str, object], cast(dict[str, object], workflow["jobs"])["propose"])
    assert job["runs-on"] == "ubuntu-24.04"
    setup = next(
        step for step in steps if "actions/setup-python@" in str(step.get("uses", ""))
    )
    assert cast(dict[str, str], setup["with"])["python-version"] == "3.11"


def test_proposal_inputs_outputs_and_gate_pin_are_separate() -> None:
    workflow = _workflow("propose-importtime-baseline.yml")
    steps = _steps(workflow, "propose")
    commands = _run_steps(steps)
    assert (
        "python -m pip install --requirement ci/requirements-candidate.txt" in commands
    )
    assert "for run in 1 2 3; do" in commands
    assert "--module packaging --module packaging.version" in commands
    assert "--warmups 1 --samples 7 --format json" in commands
    assert "importtime-check baseline propose" in commands
    for number in (1, 2, 3):
        assert f"--file .tmp/importtime-measurement-{number}.json" in commands
    assert "--runner-context gh-ubuntu-24.04" in commands
    assert "--install-context packaging-26.3" in commands
    assert "--profile gh-ubuntu-24.04" in commands
    assert "--budget packaging=1000,25" in commands
    assert "--budget packaging.version=2000,30" in commands
    assert f"--output {CANDIDATE}" in commands
    assert f"--explain > {EXPLANATION}" in commands
    upload = next(
        step
        for step in steps
        if "actions/upload-artifact@" in str(step.get("uses", ""))
    )
    upload_options = cast(dict[str, str], upload["with"])
    assert upload_options["if-no-files-found"] == "error"
    assert set(upload_options["path"].splitlines()) == {CANDIDATE, EXPLANATION}

    candidate_requirements = (EXAMPLES / "requirements-candidate.txt").read_text(
        encoding="utf-8"
    )
    check_requirements = (EXAMPLES / "requirements-importtime.txt").read_text(
        encoding="utf-8"
    )
    assert "importtime-check==0.2.0a2" in candidate_requirements.splitlines()
    assert "packaging==26.3" in candidate_requirements.splitlines()
    assert "packaging==26.3" in check_requirements.splitlines()

    gate = _workflow("check-importtime.yml")
    assert set(cast(dict[str, object], gate["on"])) == {"pull_request", "push"}
    assert gate["permissions"] == {"contents": "read"}
    gate_commands = _run_steps(_steps(gate, "check"))
    assert f"--baseline {APPROVED_BASELINE}" in gate_commands
    assert CANDIDATE not in gate_commands
    assert "baseline propose" not in gate_commands


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("trigger", "pull_request"),
        ("permission", "write"),
        ("job_permission", "write"),
        ("approved_path", APPROVED_BASELINE),
        ("commit", "git add ci/importtime-baseline.json"),
        ("refresh", "importtime-check baseline refresh --replace"),
    ],
)
def test_candidate_guard_rejects_unsafe_changes(field: str, replacement: str) -> None:
    workflow = _workflow("propose-importtime-baseline.yml")
    if field == "trigger":
        workflow["on"] = {replacement: ""}
    elif field == "permission":
        workflow["permissions"] = {"contents": replacement}
    elif field == "job_permission":
        job = cast(
            dict[str, object], cast(dict[str, object], workflow["jobs"])["propose"]
        )
        job["permissions"] = {"contents": replacement}
    else:
        steps = _steps(workflow, "propose")
        run_step = next(
            step for step in steps if "baseline propose" in str(step.get("run", ""))
        )
        run_step["run"] = f"{run_step['run']}\n{replacement}"
    assert _unsafe_candidate_workflow(workflow)
