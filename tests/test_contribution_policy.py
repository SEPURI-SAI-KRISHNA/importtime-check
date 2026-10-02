from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from tools import contribution_policy
from tools.contribution_policy import PolicyLookupError


def _issue_body(headings: tuple[str, ...], values: Mapping[str, str]) -> str:
    return "\n\n".join(
        f"### {heading}\n\n{values.get(heading, '_No response_')}"
        for heading in headings
    )


def _feature_issue() -> tuple[str, str]:
    headings = (
        "Problem to solve",
        "Proposed behavior",
        "Alternatives considered",
        "Compatibility impact",
        "Acceptance criteria",
        "Non-goals",
        "Checks",
    )
    body = _issue_body(
        headings,
        {
            "Problem to solve": "Contributions need a reliable policy.",
            "Proposed behavior": "Validate every contribution.",
            "Acceptance criteria": "Invalid contributions fail validation.",
            "Non-goals": "This does not change package behavior.",
            "Checks": (
                "- [x] I searched open and closed issues for a similar proposal.\n"
                "- [X] I understand that design discussion may precede implementation."
            ),
        },
    )
    return "feature: enforce contribution policy", body


def _bug_issue() -> tuple[str, str]:
    headings = (
        "Description",
        "Steps to reproduce",
        "Expected behavior",
        "Actual behavior",
        "importtime-check version",
        "Python version",
        "Operating system",
        "Relevant output",
        "Checks",
    )
    body = _issue_body(
        headings,
        {
            "Description": "A parsed value is incorrect.",
            "Steps to reproduce": "python -m example",
            "Expected behavior": "The value is one.",
            "Actual behavior": "The value is two.",
            "importtime-check version": "0.1.0a1",
            "Python version": "3.14",
            "Operating system": "Ubuntu 26.04",
            "Checks": (
                "- [x] I searched open and closed issues for an existing report.\n"
                "- [x] This report does not contain a security vulnerability or secret."
            ),
        },
    )
    return "bug: parse the correct value", body


def _task_issue() -> tuple[str, str]:
    headings = (
        "Summary",
        "Motivation",
        "Scope",
        "Acceptance criteria",
        "Non-goals",
        "References",
        "Checks",
    )
    body = _issue_body(
        headings,
        {
            "Summary": "Add one focused behavior.",
            "Motivation": "The next roadmap step requires it.",
            "Scope": "Implementation, tests, and documentation.",
            "Acceptance criteria": "The documented behavior passes CI.",
            "Non-goals": "No unrelated refactoring.",
            "Checks": (
                "- [x] I searched open and closed issues for duplicate work.\n"
                "- [x] This task is focused enough for one pull request."
            ),
        },
    )
    return "task: add focused behavior", body


def _pr_body(
    *,
    issue_number: int = 14,
    documentation: str = (
        "- [x] Documentation updated: updated the contributor guide.\n"
        "- [ ] No documentation change needed:"
    ),
    release_note: str = (
        "- [ ] User-visible change:\n"
        "- [x] No release note needed: repository policy only."
    ),
) -> str:
    checklist = "\n".join(
        (
            "- [x] Tests cover the changed behavior and failure paths, or the validation section explains why tests are unnecessary.",
            "- [x] Public behavior and documentation agree, or no public behavior changed.",
            "- [x] No runtime dependency or compatibility promise changed unintentionally.",
            "- [x] Commits include DCO sign-off (`Signed-off-by`).",
            "- [x] I preserved every required section of this pull request template.",
        )
    )
    return f"""## Summary

Enforce contribution policy.

## Related issue

Closes #{issue_number}

## Validation

`python -m pytest` passed.

## Compatibility and risk

Repository policy only; no package behavior changes.

## Documentation

{documentation}

## Release note

{release_note}

## Checklist

{checklist}
"""


@pytest.mark.parametrize("issue", (_bug_issue(), _feature_issue(), _task_issue()))
def test_validate_issue_accepts_every_approved_form(issue: tuple[str, str]) -> None:
    assert contribution_policy.validate_issue(*issue) == ()


def test_validate_issue_rejects_wrong_title_and_obsolete_footer() -> None:
    _, body = _feature_issue()
    body += "\n\n## Planning metadata\n\n- Assignee: someone\n"

    errors = contribution_policy.validate_issue("proposal without prefix", body)

    assert "the obsolete Planning metadata section is prohibited" in errors
    assert "Feature request title must start with 'feature: '" in errors


def test_validate_issue_rejects_changed_headings() -> None:
    title, body = _task_issue()

    errors = contribution_policy.validate_issue(
        title, body.replace("### Scope", "### Work", 1)
    )

    assert errors == ("issue body does not match an approved Issue Form",)


def test_validate_issue_ignores_heading_syntax_inside_code_fences() -> None:
    title, body = _bug_issue()
    body = body.replace(
        "python -m example",
        "```shell\npython -m example\n### this is shell input, not a section\n```",
        1,
    )

    assert contribution_policy.validate_issue(title, body) == ()


def test_validate_issue_rejects_empty_required_value_and_unchecked_box() -> None:
    title, body = _bug_issue()
    body = body.replace("A parsed value is incorrect.", "_No response_", 1)
    body = body.replace("- [x] This report", "- [ ] This report", 1)

    errors = contribution_policy.validate_issue(title, body)

    assert "required issue section 'Description' is empty" in errors
    assert "every required checklist item must be checked" in errors


def _valid_linked_issue() -> dict[str, object]:
    title, body = _feature_issue()
    return {
        "title": title,
        "body": body,
        "state": "open",
        "milestone": {"title": "0.1.0a1"},
    }


def _lookup(issue: Mapping[str, object]) -> contribution_policy.IssueLookup:
    def lookup(_: int) -> Mapping[str, object]:
        return issue

    return lookup


def test_validate_pull_request_accepts_complete_template() -> None:
    errors = contribution_policy.validate_pull_request(
        "chore: enforce contribution governance",
        _pr_body(),
        "main",
        _lookup(_valid_linked_issue()),
        labels=("enhancement", "skip-release-notes"),
    )

    assert errors == ()


def test_validate_pull_request_accepts_user_visible_release_category() -> None:
    body = _pr_body(
        release_note=(
            "- [x] User-visible change: add a documented command.\n"
            "- [ ] No release note needed:"
        )
    )

    errors = contribution_policy.validate_pull_request(
        "feat: add documented command",
        body,
        "main",
        _lookup(_valid_linked_issue()),
        labels=("enhancement",),
    )

    assert errors == ()


@pytest.mark.parametrize(
    ("body", "labels", "expected"),
    (
        (
            _pr_body(),
            ("enhancement",),
            "non-user-visible change needs the skip-release-notes label",
        ),
        (
            _pr_body(
                release_note=(
                    "- [x] User-visible change: add a documented command.\n"
                    "- [ ] No release note needed:"
                )
            ),
            ("enhancement", "skip-release-notes"),
            "user-visible change cannot use the skip-release-notes label",
        ),
        (
            _pr_body(
                release_note=(
                    "- [x] User-visible change: add a documented command.\n"
                    "- [ ] No release note needed:"
                )
            ),
            (),
            "user-visible change needs a release-category label",
        ),
    ),
)
def test_validate_pull_request_enforces_release_label_consistency(
    body: str, labels: tuple[str, ...], expected: str
) -> None:
    errors = contribution_policy.validate_pull_request(
        "chore: enforce policy",
        body,
        "main",
        _lookup(_valid_linked_issue()),
        labels=labels,
    )

    assert expected in errors


@pytest.mark.parametrize(
    ("title", "base_branch", "expected"),
    (
        ("Unstructured title", "main", "approved conventional prefix"),
        ("chore: " + "x" * 74, "main", "approved conventional prefix"),
        ("chore: valid title", "release", "base branch must be 'main'"),
    ),
)
def test_validate_pull_request_rejects_title_or_base(
    title: str, base_branch: str, expected: str
) -> None:
    errors = contribution_policy.validate_pull_request(
        title,
        _pr_body(),
        base_branch,
        _lookup(_valid_linked_issue()),
        labels=("enhancement", "skip-release-notes"),
    )

    assert any(expected in error for error in errors)


def test_validate_pull_request_requires_exact_template_and_closing_reference() -> None:
    body = _pr_body().replace("## Validation", "## Testing", 1)
    errors = contribution_policy.validate_pull_request(
        "test: validate policy",
        body,
        "main",
        _lookup(_valid_linked_issue()),
        labels=("enhancement", "skip-release-notes"),
    )
    assert "pull request body does not match the approved template" in errors

    body = _pr_body().replace("Closes #14", "Related to #14", 1)
    errors = contribution_policy.validate_pull_request(
        "test: validate policy",
        body,
        "main",
        _lookup(_valid_linked_issue()),
        labels=("enhancement", "skip-release-notes"),
    )
    assert (
        "Related issue must contain one closing reference like 'Closes #NUMBER'"
        in errors
    )


@pytest.mark.parametrize(
    ("issue_changes", "expected"),
    (
        ({"state": "closed"}, "linked issue #14 must be open"),
        ({"milestone": None}, "linked issue #14 must have a milestone"),
        ({"pull_request": {}}, "#14 is a pull request, not an issue"),
        ({"title": "wrong title"}, "linked issue #14: Feature request title"),
        ({"body": None}, "linked issue #14 has invalid metadata"),
    ),
)
def test_validate_pull_request_rejects_invalid_linked_issue(
    issue_changes: Mapping[str, object], expected: str
) -> None:
    issue = _valid_linked_issue()
    issue.update(issue_changes)

    errors = contribution_policy.validate_pull_request(
        "chore: enforce policy",
        _pr_body(),
        "main",
        _lookup(issue),
        labels=("enhancement", "skip-release-notes"),
    )

    assert any(expected in error for error in errors)


def test_validate_pull_request_reports_lookup_failure() -> None:
    def fail_lookup(_: int) -> Mapping[str, object]:
        raise PolicyLookupError("could not verify linked issue #14")

    errors = contribution_policy.validate_pull_request(
        "chore: enforce policy",
        _pr_body(),
        "main",
        fail_lookup,
        labels=("enhancement", "skip-release-notes"),
    )

    assert "could not verify linked issue #14" in errors


@pytest.mark.parametrize(
    ("body", "expected"),
    (
        (
            _pr_body(
                documentation=(
                    "- [x] Documentation updated: docs changed.\n"
                    "- [x] No documentation change needed: not needed."
                )
            ),
            "Documentation: select exactly one option",
        ),
        (
            _pr_body(
                release_note=(
                    "- [x] User-visible change:\n- [ ] No release note needed:"
                )
            ),
            "Release note: selected option 'User-visible change' needs concrete details",
        ),
        (
            _pr_body().replace("- [x] Commits include", "- [ ] Commits include"),
            "every required checklist item must be checked",
        ),
    ),
)
def test_validate_pull_request_rejects_incomplete_decisions(
    body: str, expected: str
) -> None:
    errors = contribution_policy.validate_pull_request(
        "chore: enforce policy",
        body,
        "main",
        _lookup(_valid_linked_issue()),
        labels=("enhancement", "skip-release-notes"),
    )

    assert expected in errors


def test_issue_event_cli_reports_success_and_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    title, body = _task_issue()
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps({"issue": {"title": title, "body": body}}), encoding="utf-8"
    )

    assert contribution_policy.main(("issue-event", "--event", str(event_path))) == 0
    assert "validation passed" in capsys.readouterr().out

    event_path.write_text(
        json.dumps({"issue": {"title": title, "body": "blank"}}), encoding="utf-8"
    )
    assert contribution_policy.main(("issue-event", "--event", str(event_path))) == 1
    assert "does not match an approved Issue Form" in capsys.readouterr().err


def test_file_cli_validates_issue_and_pull_request(tmp_path: Path) -> None:
    issue_title, issue_body = _feature_issue()
    issue_body_path = tmp_path / "issue.md"
    issue_body_path.write_text(issue_body, encoding="utf-8")

    assert (
        contribution_policy.main(
            (
                "issue-file",
                "--title",
                issue_title,
                "--body",
                str(issue_body_path),
            )
        )
        == 0
    )

    pr_body_path = tmp_path / "pr.md"
    pr_body_path.write_text(_pr_body(), encoding="utf-8")
    issue_json_path = tmp_path / "issue.json"
    issue = _valid_linked_issue()
    issue["number"] = 14
    issue_json_path.write_text(json.dumps(issue), encoding="utf-8")

    assert (
        contribution_policy.main(
            (
                "pr-file",
                "--title",
                "chore: enforce contribution governance",
                "--body",
                str(pr_body_path),
                "--issue-json",
                str(issue_json_path),
                "--label",
                "enhancement",
                "--label",
                "skip-release-notes",
            )
        )
        == 0
    )


def test_pr_event_cli_uses_repository_issue_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps(
            {
                "pull_request": {
                    "title": "chore: enforce contribution governance",
                    "body": _pr_body(),
                    "base": {"ref": "main"},
                    "labels": [
                        {"name": "enhancement"},
                        {"name": "skip-release-notes"},
                    ],
                },
                "repository": {"full_name": "owner/repository"},
            }
        ),
        encoding="utf-8",
    )
    observed: list[tuple[str, int, str]] = []

    def fake_fetch(
        repository: str,
        issue_number: int,
        token: str,
        *,
        api_url: str = "https://api.github.com",
    ) -> Mapping[str, object]:
        observed.append((repository, issue_number, token))
        assert api_url == "https://api.github.com"
        return _valid_linked_issue()

    monkeypatch.setattr(contribution_policy, "fetch_issue", fake_fetch)
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")

    assert contribution_policy.main(("pr-event", "--event", str(event_path))) == 0
    assert observed == [("owner/repository", 14, "test-token")]
