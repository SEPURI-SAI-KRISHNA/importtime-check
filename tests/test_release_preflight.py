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

"""Release preflight derives exact, version-scoped tracking before publication."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tools import release_preflight as release

SHA = "a" * 40
REPOSITORY = "owner/repo"
VERSION = "0.1.0a2"
MILESTONE = 2
RELEASE_ISSUE = 46


def _milestone(*, number: int = MILESTONE, title: str = VERSION) -> dict[str, Any]:
    return {"number": number, "title": title, "state": "open"}


def _issue(
    *, number: int = RELEASE_ISSUE, title: str = f"release: {VERSION}"
) -> dict[str, Any]:
    return {
        "number": number,
        "title": title,
        "state": "open",
        "milestone": {"number": MILESTONE},
    }


def _responses(endpoint: str) -> Any:
    if endpoint.startswith("git/ref/tags/"):
        return {"object": {"type": "commit", "sha": SHA}}
    if endpoint.startswith("actions/workflows/"):
        return {
            "workflow_runs": [
                {"head_sha": SHA, "event": "push", "conclusion": "success"}
            ]
        }
    if endpoint.startswith("milestones?"):
        return [_milestone()]
    if endpoint.startswith("issues?"):
        return [_issue()]
    if endpoint == f"issues/{RELEASE_ISSUE}":
        return _issue()
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
        "tag": f"v{VERSION}",
        "confirmation": f"publish {VERSION}",
        "approval": VERSION,
        "main_sha": SHA,
        "token": "token",
        "version": VERSION,
    }
    options.update(overrides)
    return release.validate_release(**options)


def test_release_preflight_accepts_second_milestone_without_historical_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def respond(repo: str, endpoint: str, token: str) -> Any:
        seen.append(endpoint)
        return _responses(endpoint)

    monkeypatch.setattr(release, "_get", respond)
    assert _validate() == SHA
    assert any(endpoint.startswith("milestones?state=open") for endpoint in seen)
    assert any(
        endpoint.startswith("issues?state=open&milestone=2") for endpoint in seen
    )
    assert f"issues/{RELEASE_ISSUE}" in seen
    assert "issues/28" not in seen
    assert "pulls/13" not in seen


@pytest.mark.parametrize(
    "change",
    [
        {"repository": "bad"},
        {"main_sha": "bad"},
        {"token": ""},
        {"tag": "v0.1.0a1"},
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


def test_release_preflight_rejects_wrong_source_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        release, "_get", lambda repo, endpoint, token: _responses(endpoint)
    )
    with pytest.raises(release.ReleasePreflightError, match="open milestone"):
        _validate(
            version="0.1.0a3",
            tag="v0.1.0a3",
            confirmation="publish 0.1.0a3",
            approval="0.1.0a3",
        )


@pytest.mark.parametrize(
    "milestones",
    [[], [_milestone(), _milestone(number=3)]],
)
def test_release_preflight_rejects_missing_or_duplicate_milestone(
    milestones: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    def respond(repo: str, endpoint: str, token: str) -> Any:
        return (
            milestones if endpoint.startswith("milestones?") else _responses(endpoint)
        )

    monkeypatch.setattr(release, "_get", respond)
    with pytest.raises(release.ReleasePreflightError, match="one open milestone"):
        _validate()


@pytest.mark.parametrize(
    "milestones",
    [
        "bad",
        ["bad"],
        [{"number": True, "title": VERSION, "state": "open"}],
        [{"number": MILESTONE, "title": VERSION, "state": "closed"}],
    ],
)
def test_release_preflight_rejects_invalid_milestone_response(
    milestones: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def respond(repo: str, endpoint: str, token: str) -> Any:
        return (
            milestones if endpoint.startswith("milestones?") else _responses(endpoint)
        )

    monkeypatch.setattr(release, "_get", respond)
    with pytest.raises(release.ReleasePreflightError, match="milestone"):
        _validate()


@pytest.mark.parametrize(
    "issues",
    [[], [_issue(), _issue(number=47)]],
)
def test_release_preflight_rejects_missing_or_duplicate_release_issue(
    issues: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    def respond(repo: str, endpoint: str, token: str) -> Any:
        return issues if endpoint.startswith("issues?") else _responses(endpoint)

    monkeypatch.setattr(release, "_get", respond)
    with pytest.raises(release.ReleasePreflightError, match="one open release"):
        _validate()


@pytest.mark.parametrize(
    "issue",
    [
        _issue(number=45, title="maintenance: prepare release"),
        _issue(number=45, title="release: 0.1.0a1"),
    ],
)
def test_release_preflight_rejects_other_open_milestone_issues(
    issue: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def respond(repo: str, endpoint: str, token: str) -> Any:
        return (
            [_issue(), issue]
            if endpoint.startswith("issues?")
            else _responses(endpoint)
        )

    monkeypatch.setattr(release, "_get", respond)
    with pytest.raises(release.ReleasePreflightError, match="open Issue #45"):
        _validate()


@pytest.mark.parametrize(
    "changed",
    [
        {"number": 47},
        {"state": "closed"},
        {"title": "release: 0.1.0a1"},
        {"milestone": {"number": 3}},
        {"milestone": {"number": True}},
        {"pull_request": {"url": "wrong type"}},
    ],
)
def test_release_issue_must_stay_open_in_the_matching_milestone(
    changed: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def respond(repo: str, endpoint: str, token: str) -> Any:
        if endpoint == f"issues/{RELEASE_ISSUE}":
            return {**_issue(), **changed}
        return _responses(endpoint)

    monkeypatch.setattr(release, "_get", respond)
    with pytest.raises(release.ReleasePreflightError, match="remain open"):
        _validate()


def test_release_preflight_paginates_milestones_and_open_issues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def respond(repo: str, endpoint: str, token: str) -> Any:
        if endpoint == "milestones?state=open&per_page=100&page=1":
            return [
                _milestone(number=index, title=f"old-{index}")
                for index in range(1, 101)
            ]
        if endpoint == "milestones?state=open&per_page=100&page=2":
            return [_milestone()]
        if endpoint == "issues?state=open&milestone=2&per_page=100&page=1":
            return [
                {**_issue(number=index), "pull_request": {"url": "pull"}}
                for index in range(100, 200)
            ]
        if endpoint == "issues?state=open&milestone=2&per_page=100&page=2":
            return [_issue()]
        return _responses(endpoint)

    monkeypatch.setattr(release, "_get", respond)
    assert _validate() == SHA


def test_release_preflight_resolves_annotated_tag_and_rejects_wrong_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def respond(repo: str, endpoint: str, token: str) -> Any:
        if endpoint.startswith("git/ref/tags/"):
            return {"object": {"type": "tag", "sha": "b" * 40}}
        if endpoint.startswith("git/tags/"):
            return {"object": {"type": "commit", "sha": SHA}}
        return _responses(endpoint)

    monkeypatch.setattr(release, "_get", respond)
    assert _validate() == SHA
    with pytest.raises(release.ReleasePreflightError, match="main commit"):
        _validate(main_sha="c" * 40)


def test_release_preflight_rejects_red_main_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    def respond(repo: str, endpoint: str, token: str) -> Any:
        if endpoint.startswith("actions/workflows/"):
            return {
                "workflow_runs": [
                    {"head_sha": SHA, "event": "push", "conclusion": "failure"}
                ]
            }
        return _responses(endpoint)

    monkeypatch.setattr(release, "_get", respond)
    with pytest.raises(release.ReleasePreflightError, match="CI"):
        _validate()


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


def test_release_cli_writes_only_reviewed_sha(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "output"
    monkeypatch.setattr(
        release, "_get", lambda repo, endpoint, token: _responses(endpoint)
    )
    monkeypatch.setattr(release, "_source_version", lambda root: VERSION)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GITHUB_REPOSITORY", REPOSITORY)
    monkeypatch.setenv("GITHUB_SHA", SHA)
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("INPUT_TAG", f"v{VERSION}")
    monkeypatch.setenv("INPUT_CONFIRM", f"publish {VERSION}")
    monkeypatch.setenv("PYPI_RELEASE_APPROVED", VERSION)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert release.main() == 0
    assert output.read_text(encoding="utf-8") == f"sha={SHA}\n"
    assert "passed" in capsys.readouterr().out
    monkeypatch.setenv("GITHUB_REF", "refs/heads/other")
    assert release.main() == 1
    assert "must run from main" in capsys.readouterr().err
