# Contributing to importtime-check

Thank you for helping improve `importtime-check`. Every change starts with an
issue created from an approved Issue Form. Blank issues and pull requests
without an open, same-repository issue are not accepted.

## Issues and planning

Choose the Bug report, Feature proposal, Design proposal, Maintenance task, or
Release checklist that best matches the work. The forms ask for the information
needed for that kind of contribution without forcing unrelated questions.
Reports containing secrets or suspected vulnerabilities must use the private
process in [SECURITY.md](SECURITY.md), never a public issue.

Maintainers assign implementation issues to a release milestone before a pull
request is opened. Milestones own release progress; labels classify the kind
of change. A project board may be introduced when concurrent work makes a
second planning view useful, but it is not another source of release truth.

Blank issues are disabled. Maintainers use review and normal triage to request
missing context; submissions are not automatically closed because prose or
headings differ.

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

Every pull request follows the tracked Apache-inspired template and contains a
closing reference such as `Closes #123` to one open, milestone-assigned issue.
Its eight sections explain the proposal, motivation, issue, user impact,
validation, compatibility and rollback, documentation and follow-up, and a
short practical checklist. Maintainers request corrections during review when
context is missing; custom code does not police contributor prose.

A design proposal and accepted design record precede changes to public APIs,
serialized formats, compatibility promises, architecture, dependencies,
security-sensitive behavior, release policy, or contributor governance.
Repository rules require a pull request and aggregate `CI` before `main` can
accept a merge.

## Release notes and changelog

Not every internal change is useful release news. Describe user-facing behavior
and migration impact in the pull request, or write `None` when it is not
applicable. Maintainers apply a generated-release-note category label to
user-visible work and `skip-release-notes` to internal-only changes.

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
