# importtime-check

[![CI](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/actions/workflows/ci.yml/badge.svg)](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/actions/workflows/ci.yml)

`importtime-check` is a planned CI gate for detecting regressions in Python
import time. It will measure imports in clean subprocesses, compare results
with deterministic baselines, and report actionable diagnostics when startup
performance regresses.

## Project status

This project is in early development and has not been released. Installation
instructions and a stable public API are not available yet.

The first planned release is `0.1.0a1`. Python 3.11 or newer will be required.

## Development

Create a virtual environment with Python 3.11 or newer, then install the
project and its unpublished development dependency group. Dependency-group
installation requires pip 25.1 or newer.

```console
python -m venv .venv
python -m pip install --upgrade "pip>=25.1"
python -m pip install --group dev --editable .
```

Run the local quality gate from the repository root:

```console
python -m ruff format --check .
python -m ruff check .
python -m mypy src tests tools
python -m pytest
```

Build validation uses fresh artifacts in the ignored `.tmp` directory:

```console
python -m build --outdir .tmp/dist
python -m twine check .tmp/dist/*
python -m tools.validate_artifacts .tmp/dist
python -m tools.smoke_wheel .tmp/dist
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the complete contribution workflow
and [SECURITY.md](SECURITY.md) for private vulnerability reporting.

## Planned focus

- Repeatable import-time measurements with noise control.
- Deterministic, reviewable baseline files.
- Absolute and relative regression thresholds for CI.
- Import-chain diagnostics for finding newly introduced heavy imports.
- A standard-library-only core with pytest support as an optional integration.

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) and
[NOTICE](NOTICE).

This is an independent open-source project. It is not affiliated with or
endorsed by the Apache Software Foundation.
