# Contributing to importtime-check

Thank you for helping improve `importtime-check`. Every change starts with an
issue created from an approved Issue Form. Blank issues and pull requests
without an open, same-repository issue are not accepted.

## Issues and planning

Choose the Bug report, Feature request, or Implementation task form and
complete every required field. Do not replace the rendered form with a custom
body. Reports containing secrets or suspected vulnerabilities must use the
private process in [SECURITY.md](SECURITY.md), never a public issue.

Maintainers assign implementation issues to a release milestone before a pull
request is opened. Milestones own release progress; labels classify the kind
of change. A project board may be introduced when concurrent work makes a
second planning view useful, but it is not another source of release truth.

The issue-policy workflow checks new, edited, and reopened issues. An issue
that bypasses every approved form is closed with instructions to submit it
again correctly. This also applies to issues created through the API or CLI.

## Development environment

Use Python 3.11 or newer and pip 25.1 or newer. From the repository root:

```console
python -m venv .venv
python -m pip install --upgrade "pip>=25.1"
python -m pip install --group dev --editable .
```

Activate the virtual environment using the command appropriate for your shell,
or invoke its Python executable directly.

## Required checks

Run the complete local gate before requesting review:

```console
python -m ruff format --check .
python -m ruff check .
python -m mypy src tests tools
python -m pytest
```

When packaging or artifact behavior changes, also run:

```console
python -m build --outdir .tmp/dist
python -m twine check .tmp/dist/*
python -m tools.validate_artifacts .tmp/dist
python -m tools.smoke_wheel .tmp/dist
```

The artifact directory must be fresh. The smoke check installs the exact wheel
offline with no dependencies and imports it outside the source path.

## Changes and tests

- Keep pull requests focused on one issue, but include the production code,
  tests, documentation, and migration details needed to make that issue whole.
- Add deterministic tests for success, boundary, and failure behavior. Unit
  tests must not require network access, production credentials, wall-clock
  sleeps, execution order, or mutable global machine state.
- Preserve the zero-runtime-dependency core unless an accepted design change
  explicitly says otherwise.
- Maintain compatibility with every Python version claimed in project metadata
  and enforced by CI.
- Do not weaken strict typing, linting, coverage, or artifact checks merely to
  make a change pass.

## Commits and pull requests

Every commit must include a Developer Certificate of Origin sign-off. Create it
with `git commit --signoff`; the resulting commit message contains a
`Signed-off-by` line. By signing off, you certify the
[Developer Certificate of Origin](https://developercertificate.org/).

Pull request titles use this conventional shape:

```text
type(optional-scope): imperative summary
```

Allowed types are `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`,
`refactor`, and `test`. Keep the complete title at 80 characters or fewer.

Every pull request must retain all sections of the tracked pull request
template and contain exactly one closing reference such as `Closes #123`. The
linked issue must still be open, use an approved Issue Form, and have a
milestone. This requirement also applies to automated dependency pull requests
before they can merge.

The body must list exact validation, explain compatibility and risk, make one
documentation decision, and make one release-note decision. Complete every
checklist item truthfully. A maintainer may request that a design record
precede a long-lived public contract.

The contribution-policy workflow reads its validator from trusted `main`; it
does not execute code from the pull request. Repository rules require both the
policy check and aggregate CI check before `main` can accept a merge.

## Release notes and changelog

Not every internal change is useful release news. Select `User-visible change`
in the pull request template and provide a concise user-facing summary when
behavior, compatibility, or documented usage changes. Select
`No release note needed` with a reason for CI, tests, refactoring, and other
internal maintenance. User-visible changes need one generated-release-note
category label; internal-only changes use `skip-release-notes`. The policy
check rejects a release-note selection that contradicts these labels.

GitHub generated release notes group merged pull requests by labels. The
project does not require every pull request to edit one shared `CHANGELOG.md`;
that produces noise and merge conflicts for non-user-facing work. A curated
changelog or per-pull-request news fragments may be added through a dedicated
issue when release volume, backports, or multiple concurrent contributors make
them valuable.

## Security

Do not report suspected vulnerabilities in a public issue. Follow
[SECURITY.md](SECURITY.md) for private reporting instructions.

This project is independent and is not affiliated with or endorsed by the
Apache Software Foundation.
