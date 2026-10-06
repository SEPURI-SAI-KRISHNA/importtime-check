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

"""Check every pull-request commit for an author-matching DCO sign-off."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_SIGNOFF = re.compile(r"^Signed-off-by: .+ <([^<>\s]+@[^<>\s]+)>[ \t]*$", re.M)


class DcoError(ValueError):
    """A pull request cannot pass its DCO gate."""


def _page(repository: str, number: int, page: int, token: str) -> list[Any]:
    url = (
        f"https://api.github.com/repos/{repository}/pulls/{number}/commits"
        f"?per_page=100&page={page}"
    )
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            result: Any = json.load(response)
    except (OSError, URLError, ValueError) as error:
        raise DcoError(f"cannot inspect pull-request commits: {error}") from error
    if not isinstance(result, list):
        raise DcoError("commit API returned an invalid response")
    return result


def check_dco(repository: str, number: int, token: str) -> int:
    """Return the number of commits only when every author signed off."""
    if _REPOSITORY.fullmatch(repository) is None or number < 1 or not token:
        raise DcoError("repository, pull-request number, or token is invalid")
    count = 0
    for page in range(1, 102):
        commits = _page(repository, number, page, token)
        for item in commits:
            if not isinstance(item, dict):
                raise DcoError("commit API returned an invalid item")
            details = item.get("commit")
            author = details.get("author") if isinstance(details, dict) else None
            message = details.get("message") if isinstance(details, dict) else None
            email = author.get("email") if isinstance(author, dict) else None
            sha = item.get("sha")
            if not all(isinstance(value, str) for value in (message, email, sha)):
                raise DcoError("commit API omitted author, message, or SHA")
            assert isinstance(message, str)
            assert isinstance(email, str)
            assert isinstance(sha, str)
            signoffs = {match.casefold() for match in _SIGNOFF.findall(message)}
            if email.casefold() not in signoffs:
                raise DcoError(f"commit {sha[:12]} has no author-matching DCO sign-off")
            count += 1
        if len(commits) < 100:
            break
    else:
        raise DcoError("pull request has too many commits to validate")
    if count == 0:
        raise DcoError("pull request has no commits")
    return count


def main(argv: Sequence[str] | None = None) -> int:
    """Run the read-only DCO gate in CI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pull-request", type=int, required=True)
    arguments = parser.parse_args(argv)
    try:
        count = check_dco(
            arguments.repository,
            arguments.pull_request,
            os.environ.get("GITHUB_TOKEN", ""),
        )
    except DcoError as error:
        print(f"DCO check failed: {error}", file=sys.stderr)
        return 1
    print(f"DCO check passed: {count} signed commit(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
