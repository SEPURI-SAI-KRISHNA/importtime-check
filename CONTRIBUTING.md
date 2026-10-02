# Contributing to importtime-check

Thank you for helping improve `importtime-check`. The project is pre-alpha, so
please open or reference an issue before investing in a public API, serialized
format, compatibility, dependency, or architecture change.

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

Pull requests should link their issue, explain compatibility and security
impact, and list the exact validation performed. A maintainer may request that
a design record precede a long-lived public contract.

## Security

Do not report suspected vulnerabilities in a public issue. Follow
[SECURITY.md](SECURITY.md) for private reporting instructions.

This project is independent and is not affiliated with or endorsed by the
Apache Software Foundation.
