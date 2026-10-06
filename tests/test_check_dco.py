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

"""Read-only commit sign-off gate used by the required CI workflow."""

from __future__ import annotations

from typing import Any

import pytest

from tools import check_dco as dco


def _commit(message: str, email: str = "person@example.com") -> dict[str, Any]:
    return {
        "sha": "a" * 40,
        "commit": {"author": {"email": email}, "message": message},
    }


def test_dco_accepts_matching_author_and_checks_all_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = {
        1: [_commit("change\n\nSigned-off-by: Person <PERSON@example.com>")] * 100,
        2: [_commit("fix\n\nSigned-off-by: Person <person@example.com>")],
    }
    monkeypatch.setattr(dco, "_page", lambda repo, number, page, token: pages[page])
    assert dco.check_dco("owner/repo", 7, "token") == 101


@pytest.mark.parametrize(
    "commits,expected",
    [
        ([], "no commits"),
        ([_commit("no sign-off")], "author-matching"),
        ([_commit("Signed-off-by: Other <other@example.com>")], "author-matching"),
        ([{"sha": "a" * 40, "commit": {"message": "x"}}], "omitted"),
        (["invalid"], "invalid item"),
    ],
)
def test_dco_rejects_missing_or_malformed_commits(
    monkeypatch: pytest.MonkeyPatch, commits: list[Any], expected: str
) -> None:
    monkeypatch.setattr(dco, "_page", lambda repo, number, page, token: commits)
    with pytest.raises(dco.DcoError, match=expected):
        dco.check_dco("owner/repo", 7, "token")


@pytest.mark.parametrize(
    ("repository", "number", "token"),
    [("bad", 7, "token"), ("owner/repo", 0, "token"), ("owner/repo", 7, "")],
)
def test_dco_rejects_invalid_inputs(repository: str, number: int, token: str) -> None:
    with pytest.raises(dco.DcoError, match="invalid"):
        dco.check_dco(repository, number, token)


def test_dco_cli_reports_success_and_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(
        dco,
        "_page",
        lambda repo, number, page, token: [
            _commit("Signed-off-by: Person <person@example.com>")
        ],
    )
    assert dco.main(["--repository", "owner/repo", "--pull-request", "7"]) == 0
    assert "1 signed commit" in capsys.readouterr().out
    monkeypatch.setattr(dco, "_page", lambda repo, number, page, token: [])
    assert dco.main(["--repository", "owner/repo", "--pull-request", "7"]) == 1
    assert "DCO check failed" in capsys.readouterr().err
