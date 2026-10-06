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

"""Release workflow rejects mismatched tags, red CI, and open scope."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tools import release_preflight as release

SHA = "a" * 40
REPOSITORY = "owner/repo"


def _responses(
    endpoint: str, *, ci: str = "success", issue: int = 28, pr: str = "closed"
) -> Any:
    if endpoint.startswith("git/ref/tags/"):
        return {"object": {"type": "commit", "sha": SHA}}
    if endpoint.startswith("actions/workflows/"):
        return {"workflow_runs": [{"head_sha": SHA, "event": "push", "conclusion": ci}]}
    if endpoint.startswith("issues?"):
        return [{"number": issue}]
    if endpoint == "issues/28":
        return {"state": "open", "milestone": {"number": 1}}
    if endpoint == "pulls/13":
        return {"state": pr}
    if endpoint == "environments/pypi":
        return {
            "name": "pypi",
            "protection_rules": [
                {"type": "required_reviewers", "reviewers": [{"type": "User"}]}
            ],
            "deployment_branch_policy": {"protected_branches": True},
        }
    raise AssertionError(endpoint)


def _validate(**overrides: Any) -> str:
    options: dict[str, Any] = {
        "repository": REPOSITORY,
        "tag": "v0.1.0a1",
        "confirmation": "publish 0.1.0a1",
        "approval": "0.1.0a1",
        "main_sha": SHA,
        "token": "token",
        "version": "0.1.0a1",
        "milestone": 1,
    }
    options.update(overrides)
    return release.validate_release(**options)


def test_release_preflight_accepts_only_exact_reviewed_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        release, "_get", lambda repo, endpoint, token: _responses(endpoint)
    )
    assert _validate() == SHA


@pytest.mark.parametrize(
    "change",
    [
        {"repository": "bad"},
        {"main_sha": "bad"},
        {"token": ""},
        {"milestone": 0},
        {"tag": "v0.1.0a2"},
        {"confirmation": "publish anything"},
        {"approval": ""},
    ],
)
def test_release_preflight_rejects_invalid_authorization(
    change: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        release, "_get", lambda repo, endpoint, token: _responses(endpoint)
    )
    with pytest.raises(release.ReleasePreflightError):
        _validate(**change)


@pytest.mark.parametrize(
    ("ci", "issue", "pr", "message"),
    [
        ("failure", 28, "closed", "CI"),
        ("success", 27, "closed", "open Issue"),
        ("success", 28, "open", "PR #13"),
    ],
)
def test_release_preflight_rejects_remote_blockers(
    ci: str, issue: int, pr: str, message: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        release,
        "_get",
        lambda repo, endpoint, token: _responses(endpoint, ci=ci, issue=issue, pr=pr),
    )
    with pytest.raises(release.ReleasePreflightError, match=message):
        _validate()


def test_release_preflight_resolves_annotated_tag_and_rejects_wrong_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def annotated(repo: str, endpoint: str, token: str) -> Any:
        if endpoint.startswith("git/ref/tags/"):
            return {"object": {"type": "tag", "sha": "b" * 40}}
        if endpoint.startswith("git/tags/"):
            return {"object": {"type": "commit", "sha": SHA}}
        return _responses(endpoint)

    monkeypatch.setattr(release, "_get", annotated)
    assert _validate() == SHA
    with pytest.raises(release.ReleasePreflightError, match="main commit"):
        _validate(main_sha="c" * 40)


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({"name": "wrong"}, "missing"),
        ({"name": "pypi", "protection_rules": []}, "required reviewers"),
        (
            {
                "name": "pypi",
                "protection_rules": [
                    {"type": "required_reviewers", "reviewers": [{"type": "User"}]}
                ],
                "deployment_branch_policy": None,
            },
            "branch restrictions",
        ),
    ],
)
def test_release_preflight_requires_protected_environment(
    environment: dict[str, Any], message: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def respond(repo: str, endpoint: str, token: str) -> Any:
        return environment if endpoint == "environments/pypi" else _responses(endpoint)

    monkeypatch.setattr(release, "_get", respond)
    with pytest.raises(release.ReleasePreflightError, match=message):
        _validate()


def test_release_issue_must_stay_open(monkeypatch: pytest.MonkeyPatch) -> None:
    def respond(repo: str, endpoint: str, token: str) -> Any:
        return (
            {"state": "closed", "milestone": {"number": 1}}
            if endpoint == "issues/28"
            else _responses(endpoint)
        )

    monkeypatch.setattr(release, "_get", respond)
    with pytest.raises(release.ReleasePreflightError, match="remain open"):
        _validate()


def test_release_cli_writes_only_reviewed_sha(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "output"
    monkeypatch.setattr(
        release, "_get", lambda repo, endpoint, token: _responses(endpoint)
    )
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    monkeypatch.setenv("GITHUB_SHA", SHA)
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("INPUT_TAG", "v0.1.0a1")
    monkeypatch.setenv("INPUT_CONFIRM", "publish 0.1.0a1")
    monkeypatch.setenv("PYPI_RELEASE_APPROVED", "0.1.0a1")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert release.main() == 0
    assert output.read_text(encoding="utf-8") == f"sha={SHA}\n"
    assert "passed" in capsys.readouterr().out
    monkeypatch.setenv("GITHUB_REF", "refs/heads/other")
    assert release.main() == 1
    assert "must run from main" in capsys.readouterr().err
