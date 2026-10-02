"""Validate issue and pull request contribution policy."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_PLANNING_METADATA = re.compile(
    r"^## Planning metadata\s*$", re.IGNORECASE | re.MULTILINE
)
_PR_TITLE = re.compile(
    r"(?:build|chore|ci|docs|feat|fix|perf|refactor|test)"
    r"(?:\([a-z0-9][a-z0-9._-]*\))?!?: [^\s].*"
)
_CLOSING_REFERENCE = re.compile(
    r"(?:closes|fixes|resolves) #([1-9][0-9]*)", re.IGNORECASE
)
_CHECKBOX = re.compile(r"- \[([ xX])\] (.+)")


@dataclass(frozen=True, slots=True)
class IssueForm:
    """One accepted rendered Issue Form contract."""

    name: str
    title_prefix: str
    headings: tuple[str, ...]
    required: tuple[str, ...]
    checks: tuple[str, ...]


_BUG_FORM = IssueForm(
    name="Bug report",
    title_prefix="bug: ",
    headings=(
        "Description",
        "Steps to reproduce",
        "Expected behavior",
        "Actual behavior",
        "importtime-check version",
        "Python version",
        "Operating system",
        "Relevant output",
        "Checks",
    ),
    required=(
        "Description",
        "Steps to reproduce",
        "Expected behavior",
        "Actual behavior",
        "importtime-check version",
        "Python version",
        "Operating system",
    ),
    checks=(
        "I searched open and closed issues for an existing report.",
        "This report does not contain a security vulnerability or secret.",
    ),
)
_FEATURE_FORM = IssueForm(
    name="Feature request",
    title_prefix="feature: ",
    headings=(
        "Problem to solve",
        "Proposed behavior",
        "Alternatives considered",
        "Compatibility impact",
        "Acceptance criteria",
        "Non-goals",
        "Checks",
    ),
    required=(
        "Problem to solve",
        "Proposed behavior",
        "Acceptance criteria",
        "Non-goals",
    ),
    checks=(
        "I searched open and closed issues for a similar proposal.",
        "I understand that design discussion may precede implementation.",
    ),
)
_TASK_FORM = IssueForm(
    name="Implementation task",
    title_prefix="task: ",
    headings=(
        "Summary",
        "Motivation",
        "Scope",
        "Acceptance criteria",
        "Non-goals",
        "References",
        "Checks",
    ),
    required=("Summary", "Motivation", "Scope", "Acceptance criteria", "Non-goals"),
    checks=(
        "I searched open and closed issues for duplicate work.",
        "This task is focused enough for one pull request.",
    ),
)
_ISSUE_FORMS = (_BUG_FORM, _FEATURE_FORM, _TASK_FORM)

_PR_HEADINGS = (
    "Summary",
    "Related issue",
    "Validation",
    "Compatibility and risk",
    "Documentation",
    "Release note",
    "Checklist",
)
_PR_CHECKS = (
    "Tests cover the changed behavior and failure paths, or the validation "
    "section explains why tests are unnecessary.",
    "Public behavior and documentation agree, or no public behavior changed.",
    "No runtime dependency or compatibility promise changed unintentionally.",
    "Commits include DCO sign-off (`Signed-off-by`).",
    "I preserved every required section of this pull request template.",
)

IssueLookup = Callable[[int], Mapping[str, object]]


class PolicyLookupError(RuntimeError):
    """Raised when linked-issue metadata cannot be verified."""


def _sections(body: str, level: int) -> tuple[tuple[str, ...], dict[str, str]]:
    marker = "#" * level
    pattern = re.compile(rf"^{marker} ([^\r\n]+?)[ \t]*$", re.MULTILINE)
    matches = list(pattern.finditer(_mask_noncontent(body)))
    names = tuple(match.group(1) for match in matches)
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[match.group(1)] = body[match.end() : end].strip()
    return names, sections


def _mask_noncontent(body: str) -> str:
    masked = _COMMENT.sub(lambda match: re.sub(r"[^\r\n]", " ", match.group()), body)
    result: list[str] = []
    fence_character = ""
    fence_length = 0
    for line in masked.splitlines(keepends=True):
        fence = re.match(r"[ \t]{0,3}(`{3,}|~{3,})", line)
        inside_fence = bool(fence_character)
        if fence is not None:
            marker = fence.group(1)
            if not inside_fence:
                fence_character = marker[0]
                fence_length = len(marker)
                inside_fence = True
            elif marker[0] == fence_character and len(marker) >= fence_length:
                fence_character = ""
                fence_length = 0
        if inside_fence:
            result.append(re.sub(r"[^\r\n]", " ", line))
        else:
            result.append(line)
    return "".join(result)


def _without_comments(value: str) -> str:
    return _COMMENT.sub("", value).strip()


def _is_meaningful(value: str) -> bool:
    cleaned = _without_comments(value)
    return bool(cleaned) and cleaned.casefold() != "_no response_"


def _validate_checklist(section: str, expected: tuple[str, ...]) -> tuple[str, ...]:
    cleaned = _without_comments(section)
    parsed: list[tuple[bool, str]] = []
    for line in cleaned.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = _CHECKBOX.fullmatch(stripped)
        if match is None:
            return ("checklist contains text outside the approved checkboxes",)
        parsed.append((match.group(1).casefold() == "x", match.group(2)))

    labels = tuple(label for _, label in parsed)
    errors: list[str] = []
    if labels != expected:
        errors.append("checklist does not match the approved template")
    if parsed and not all(checked for checked, _ in parsed):
        errors.append("every required checklist item must be checked")
    return tuple(errors)


def _validate_choice(
    section: str, first_label: str, second_label: str
) -> tuple[tuple[str, ...], str | None]:
    cleaned = _without_comments(section)
    options: list[tuple[bool, str, str]] = []
    for line in cleaned.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = re.fullmatch(r"- \[([ xX])\] ([^:]+):\s*(.*)", stripped)
        if match is None:
            return (("selection contains text outside the approved options",), None)
        options.append(
            (match.group(1).casefold() == "x", match.group(2), match.group(3))
        )

    errors: list[str] = []
    labels = tuple(label for _, label, _ in options)
    if labels != (first_label, second_label):
        errors.append("selection does not match the approved template")
        return tuple(errors), None

    selected = [(label, detail) for checked, label, detail in options if checked]
    if len(selected) != 1:
        errors.append("select exactly one option")
        selected_label = None
    elif not _is_meaningful(selected[0][1]):
        errors.append(f"selected option '{selected[0][0]}' needs concrete details")
        selected_label = selected[0][0]
    else:
        selected_label = selected[0][0]
    return tuple(errors), selected_label


def validate_issue(title: str, body: str) -> tuple[str, ...]:
    """Validate an issue title and rendered Issue Form body."""
    errors: list[str] = []
    if _PLANNING_METADATA.search(body):
        errors.append("the obsolete Planning metadata section is prohibited")

    headings, sections = _sections(body, level=3)
    form = next(
        (candidate for candidate in _ISSUE_FORMS if headings == candidate.headings),
        None,
    )
    if form is None:
        errors.append("issue body does not match an approved Issue Form")
        return tuple(errors)

    if (
        not title.startswith(form.title_prefix)
        or not title[len(form.title_prefix) :].strip()
    ):
        errors.append(f"{form.name} title must start with '{form.title_prefix}'")

    for heading in form.required:
        if not _is_meaningful(sections[heading]):
            errors.append(f"required issue section '{heading}' is empty")
    errors.extend(_validate_checklist(sections["Checks"], form.checks))
    return tuple(errors)


def validate_pull_request(
    title: str,
    body: str,
    base_branch: str,
    issue_lookup: IssueLookup,
    *,
    labels: Collection[str],
) -> tuple[str, ...]:
    """Validate a pull request and its closing issue reference."""
    errors: list[str] = []
    if base_branch != "main":
        errors.append("pull request base branch must be 'main'")
    if len(title) > 80 or _PR_TITLE.fullmatch(title) is None:
        errors.append("pull request title must use an approved conventional prefix")
    if _PLANNING_METADATA.search(body):
        errors.append("the obsolete Planning metadata section is prohibited")

    headings, sections = _sections(body, level=2)
    if headings != _PR_HEADINGS:
        errors.append("pull request body does not match the approved template")
        return tuple(errors)

    for heading in ("Summary", "Validation", "Compatibility and risk"):
        if not _is_meaningful(sections[heading]):
            errors.append(f"required pull request section '{heading}' is empty")

    related = _without_comments(sections["Related issue"])
    reference = _CLOSING_REFERENCE.fullmatch(related)
    if reference is None:
        errors.append(
            "Related issue must contain one closing reference like 'Closes #NUMBER'"
        )
    else:
        issue_number = int(reference.group(1))
        try:
            issue = issue_lookup(issue_number)
        except PolicyLookupError as error:
            errors.append(str(error))
        else:
            if "pull_request" in issue:
                errors.append(f"#{issue_number} is a pull request, not an issue")
            if issue.get("state") != "open":
                errors.append(f"linked issue #{issue_number} must be open")
            if issue.get("milestone") is None:
                errors.append(f"linked issue #{issue_number} must have a milestone")
            issue_title = issue.get("title")
            issue_body = issue.get("body")
            if not isinstance(issue_title, str) or not isinstance(issue_body, str):
                errors.append(f"linked issue #{issue_number} has invalid metadata")
            else:
                issue_errors = validate_issue(issue_title, issue_body)
                errors.extend(
                    f"linked issue #{issue_number}: {error}" for error in issue_errors
                )

    documentation_errors, _ = _validate_choice(
        sections["Documentation"],
        "Documentation updated",
        "No documentation change needed",
    )
    errors.extend(f"Documentation: {error}" for error in documentation_errors)
    release_errors, release_selection = _validate_choice(
        sections["Release note"],
        "User-visible change",
        "No release note needed",
    )
    errors.extend(f"Release note: {error}" for error in release_errors)
    release_labels = {
        "breaking-change",
        "enhancement",
        "bug",
        "documentation",
        "dependencies",
    }
    if release_selection == "User-visible change":
        if "skip-release-notes" in labels:
            errors.append("user-visible change cannot use the skip-release-notes label")
        if release_labels.isdisjoint(labels):
            errors.append("user-visible change needs a release-category label")
    elif (
        release_selection == "No release note needed"
        and "skip-release-notes" not in labels
    ):
        errors.append("non-user-visible change needs the skip-release-notes label")
    errors.extend(_validate_checklist(sections["Checklist"], _PR_CHECKS))
    return tuple(errors)


def fetch_issue(
    repository: str,
    issue_number: int,
    token: str,
    *,
    api_url: str = "https://api.github.com",
) -> Mapping[str, object]:
    """Fetch one same-repository issue through GitHub's REST API."""
    url = f"{api_url.rstrip('/')}/repos/{repository}/issues/{issue_number}"
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "importtime-check-contribution-policy",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=15) as response:
            payload = json.load(response)
    except HTTPError as error:
        raise PolicyLookupError(
            f"could not verify linked issue #{issue_number}: GitHub returned {error.code}"
        ) from error
    except (TimeoutError, URLError) as error:
        raise PolicyLookupError(
            f"could not verify linked issue #{issue_number}: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise PolicyLookupError(
            f"could not verify linked issue #{issue_number}: invalid GitHub response"
        )
    return cast(dict[str, object], payload)


def _load_json_object(path: Path, description: str) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PolicyLookupError(f"could not read {description}: {error}") from error
    if not isinstance(payload, dict):
        raise PolicyLookupError(f"{description} must be a JSON object")
    return cast(dict[str, object], payload)


def _read_text(path: Path, description: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise PolicyLookupError(f"could not read {description}: {error}") from error


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise PolicyLookupError(f"event payload is missing object '{name}'")
    return cast(dict[str, object], value)


def _text(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise PolicyLookupError(f"event payload is missing text '{name}'")
    return value


def _validate_issue_event(event: Mapping[str, object]) -> tuple[str, ...]:
    issue = _mapping(event.get("issue"), "issue")
    return validate_issue(
        _text(issue.get("title"), "issue.title"),
        _text(issue.get("body"), "issue.body"),
    )


def _validate_pr_event(event: Mapping[str, object], token: str) -> tuple[str, ...]:
    pull_request = _mapping(event.get("pull_request"), "pull_request")
    base = _mapping(pull_request.get("base"), "pull_request.base")
    repository = _mapping(event.get("repository"), "repository")
    repository_name = _text(repository.get("full_name"), "repository.full_name")
    raw_labels = pull_request.get("labels")
    if not isinstance(raw_labels, list):
        raise PolicyLookupError("event payload is missing list 'pull_request.labels'")
    labels: list[str] = []
    for index, raw_label in enumerate(raw_labels):
        label = _mapping(raw_label, f"pull_request.labels[{index}]")
        labels.append(_text(label.get("name"), f"pull_request.labels[{index}].name"))

    def lookup(issue_number: int) -> Mapping[str, object]:
        return fetch_issue(repository_name, issue_number, token)

    return validate_pull_request(
        _text(pull_request.get("title"), "pull_request.title"),
        _text(pull_request.get("body"), "pull_request.body"),
        _text(base.get("ref"), "pull_request.base.ref"),
        lookup,
        labels=labels,
    )


def _print_errors(errors: tuple[str, ...]) -> None:
    for error in errors:
        escaped = error.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::error title=Contribution policy::{escaped}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    """Run contribution policy validation for one GitHub event payload."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    issue_event = commands.add_parser("issue-event")
    issue_event.add_argument("--event", type=Path, required=True)
    pr_event = commands.add_parser("pr-event")
    pr_event.add_argument("--event", type=Path, required=True)

    issue_file = commands.add_parser("issue-file")
    issue_file.add_argument("--title", required=True)
    issue_file.add_argument("--body", type=Path, required=True)

    pr_file = commands.add_parser("pr-file")
    pr_file.add_argument("--title", required=True)
    pr_file.add_argument("--body", type=Path, required=True)
    pr_file.add_argument("--base", default="main")
    pr_file.add_argument("--issue-json", type=Path, required=True)
    pr_file.add_argument("--label", action="append", default=[])

    arguments = parser.parse_args(argv)

    try:
        if arguments.command == "issue-event":
            event = _load_json_object(arguments.event, "event payload")
            errors = _validate_issue_event(event)
        elif arguments.command == "pr-event":
            event = _load_json_object(arguments.event, "event payload")
            token = os.environ.get("GITHUB_TOKEN", "")
            if not token:
                raise PolicyLookupError(
                    "GITHUB_TOKEN is required for pull request policy"
                )
            errors = _validate_pr_event(event, token)
        elif arguments.command == "issue-file":
            errors = validate_issue(
                arguments.title,
                _read_text(arguments.body, "issue body"),
            )
        else:
            issue = _load_json_object(arguments.issue_json, "issue metadata")

            def local_lookup(issue_number: int) -> Mapping[str, object]:
                if issue.get("number") != issue_number:
                    raise PolicyLookupError(
                        f"issue metadata does not describe linked issue #{issue_number}"
                    )
                return issue

            errors = validate_pull_request(
                arguments.title,
                _read_text(arguments.body, "pull request body"),
                arguments.base,
                local_lookup,
                labels=arguments.label,
            )
    except PolicyLookupError as error:
        errors = (str(error),)

    if errors:
        _print_errors(errors)
        return 1
    print("contribution policy validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
