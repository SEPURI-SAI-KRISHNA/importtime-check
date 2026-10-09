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

"""Fail-closed, read-only checks before a deliberate PyPI release run."""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_SHA = re.compile(r"[0-9a-f]{40}\Z")


class ReleasePreflightError(ValueError):
    """The requested release is not safe to publish."""


def _get(repository: str, endpoint: str, token: str) -> Any:
    request = Request(
        f"https://api.github.com/repos/{repository}/{endpoint}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.load(response)
    except (OSError, URLError, ValueError) as error:
        raise ReleasePreflightError(
            f"GitHub check failed for {endpoint}: {error}"
        ) from error


def _source_version(root: Path) -> str:
    source = root / "src" / "importtime_check" / "_version.py"
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as error:
        raise ReleasePreflightError("cannot read the version source") from error
    versions = [
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "__version__"
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ]
    if len(versions) != 1:
        raise ReleasePreflightError("version source must contain one literal")
    return versions[0]


def _tag_commit(repository: str, tag: str, token: str) -> str:
    reference = _get(repository, f"git/ref/tags/{quote(tag, safe='')}", token)
    if not isinstance(reference, dict) or not isinstance(reference.get("object"), dict):
        raise ReleasePreflightError("tag reference is invalid")
    target = reference["object"]
    for _ in range(3):
        kind = target.get("type")
        sha = target.get("sha")
        if not isinstance(sha, str) or _SHA.fullmatch(sha) is None:
            raise ReleasePreflightError("tag target SHA is invalid")
        if kind == "commit":
            return sha
        if kind != "tag":
            raise ReleasePreflightError("tag does not point to a commit")
        annotated = _get(repository, f"git/tags/{sha}", token)
        if not isinstance(annotated, dict) or not isinstance(
            annotated.get("object"), dict
        ):
            raise ReleasePreflightError("annotated tag is invalid")
        target = annotated["object"]
    raise ReleasePreflightError("tag indirection is too deep")


def _open_milestone(repository: str, token: str, version: str) -> int:
    matches: list[int] = []
    for page in range(1, 102):
        items = _get(
            repository, f"milestones?state=open&per_page=100&page={page}", token
        )
        if not isinstance(items, list):
            raise ReleasePreflightError("milestone response is invalid")
        for item in items:
            if (
                not isinstance(item, dict)
                or type(item.get("number")) is not int
                or item["number"] < 1
                or not isinstance(item.get("title"), str)
                or item.get("state") != "open"
            ):
                raise ReleasePreflightError("milestone is invalid")
            if item["title"] == version:
                matches.append(item["number"])
        if len(items) < 100:
            break
    else:
        raise ReleasePreflightError("too many milestones to validate")
    if len(matches) != 1:
        raise ReleasePreflightError(
            f"expected one open milestone titled {version!r}; found {len(matches)}"
        )
    return matches[0]


def _check_milestone(repository: str, token: str, milestone: int, version: str) -> int:
    release_issues: list[int] = []
    for page in range(1, 102):
        items = _get(
            repository,
            f"issues?state=open&milestone={milestone}&per_page=100&page={page}",
            token,
        )
        if not isinstance(items, list):
            raise ReleasePreflightError("milestone response is invalid")
        for item in items:
            if (
                not isinstance(item, dict)
                or type(item.get("number")) is not int
                or item["number"] < 1
                or item.get("state") != "open"
                or not isinstance(item.get("title"), str)
                or not isinstance(item.get("milestone"), dict)
                or type(item["milestone"].get("number")) is not int
                or item["milestone"].get("number") != milestone
            ):
                raise ReleasePreflightError("milestone issue is invalid")
            if "pull_request" in item:
                continue
            if item["title"] == f"release: {version}":
                release_issues.append(item["number"])
            else:
                raise ReleasePreflightError(
                    f"milestone still has open Issue #{item['number']}"
                )
        if len(items) < 100:
            break
    else:
        raise ReleasePreflightError("milestone has too many issues to validate")
    if len(release_issues) != 1:
        raise ReleasePreflightError(
            f"expected one open release issue titled 'release: {version}' "
            "in the milestone; "
            f"found {len(release_issues)}"
        )
    number = release_issues[0]
    release_issue = _get(repository, f"issues/{number}", token)
    release_milestone = (
        release_issue.get("milestone") if isinstance(release_issue, dict) else None
    )
    if (
        not isinstance(release_issue, dict)
        or release_issue.get("number") != number
        or release_issue.get("state") != "open"
        or release_issue.get("title") != f"release: {version}"
        or "pull_request" in release_issue
        or not isinstance(release_milestone, dict)
        or type(release_milestone.get("number")) is not int
        or release_milestone.get("number") != milestone
    ):
        raise ReleasePreflightError(
            f"release: {version} issue must remain open in the milestone"
        )
    return number


def validate_release(
    *,
    repository: str,
    tag: str,
    confirmation: str,
    approval: str,
    main_sha: str,
    token: str,
    version: str,
) -> str:
    """Return the immutable release commit after all remote checks pass."""
    if _REPOSITORY.fullmatch(repository) is None or _SHA.fullmatch(main_sha) is None:
        raise ReleasePreflightError("repository or main commit is invalid")
    if not token:
        raise ReleasePreflightError("GitHub token is missing")
    if tag != f"v{version}" or confirmation != f"publish {version}":
        raise ReleasePreflightError("tag or manual confirmation does not match version")
    if approval != version:
        raise ReleasePreflightError("PYPI_RELEASE_APPROVED must match the version")
    sha = _tag_commit(repository, tag, token)
    if sha != main_sha:
        raise ReleasePreflightError(
            "release tag must point to the dispatched main commit"
        )
    runs = _get(
        repository,
        f"actions/workflows/ci.yml/runs?branch=main&event=push&head_sha={sha}&per_page=20",
        token,
    )
    if not isinstance(runs, dict) or not isinstance(runs.get("workflow_runs"), list):
        raise ReleasePreflightError("CI run response is invalid")
    matching = [
        run
        for run in runs["workflow_runs"]
        if isinstance(run, dict)
        and run.get("head_sha") == sha
        and run.get("event") == "push"
    ]
    if not matching or matching[0].get("conclusion") != "success":
        raise ReleasePreflightError("latest main CI for the tag commit is not green")
    milestone = _open_milestone(repository, token, version)
    _check_milestone(repository, token, milestone, version)
    environment = _get(repository, "environments/pypi", token)
    if not isinstance(environment, dict) or environment.get("name") != "pypi":
        raise ReleasePreflightError("pypi environment is missing")
    rules = environment.get("protection_rules")
    branch_policy = environment.get("deployment_branch_policy")
    if not isinstance(rules, list) or not any(
        isinstance(rule, dict)
        and rule.get("type") == "required_reviewers"
        and isinstance(rule.get("reviewers"), list)
        and bool(rule["reviewers"])
        for rule in rules
    ):
        raise ReleasePreflightError("pypi environment needs required reviewers")
    if not isinstance(branch_policy, dict) or not (
        branch_policy.get("protected_branches") is True
        or branch_policy.get("custom_branch_policies") is True
    ):
        raise ReleasePreflightError("pypi environment needs branch restrictions")
    return sha


def main() -> int:
    """Validate workflow inputs and write the reviewed commit to GITHUB_OUTPUT."""
    try:
        if os.environ.get("GITHUB_REF") != "refs/heads/main":
            raise ReleasePreflightError("release dispatch must run from main")
        version = _source_version(Path(__file__).resolve().parents[1])
        sha = validate_release(
            repository=os.environ.get("GITHUB_REPOSITORY", ""),
            tag=os.environ.get("INPUT_TAG", ""),
            confirmation=os.environ.get("INPUT_CONFIRM", ""),
            approval=os.environ.get("PYPI_RELEASE_APPROVED", ""),
            main_sha=os.environ.get("GITHUB_SHA", ""),
            token=os.environ.get("GITHUB_TOKEN", ""),
            version=version,
        )
        output = os.environ.get("GITHUB_OUTPUT", "")
        if not output:
            raise ReleasePreflightError("GITHUB_OUTPUT is missing")
        with Path(output).open("a", encoding="utf-8") as handle:
            handle.write(f"sha={sha}\n")
    except (OSError, ReleasePreflightError) as error:
        print(f"release preflight failed: {error}", file=sys.stderr)
        return 1
    print(f"release preflight passed: {sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
