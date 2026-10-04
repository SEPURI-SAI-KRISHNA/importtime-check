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

The numeric stderr produced by CPython's `-X importtime` option can already be
parsed without executing a subprocess:

```python
from importtime_check import parse_importtime

result = parse_importtime(
    "import time: self [us] | cumulative | imported package\n"
    "import time:        12 |         34 | example"
)
event = result.events[0]
assert (event.module, event.self_us, event.cumulative_us, event.depth) == (
    "example",
    12,
    34,
    0,
)
```

This API remains pre-alpha and may change before the first stable release.

To measure one installed module in a fresh CPython process:

```python
from importtime_check import measure_import

measurement = measure_import("json")
print(measurement.target_event.cumulative_us)  # integer microseconds
```

The target must be installed in the selected interpreter. The child uses
Python's isolated mode, so the current directory and user site packages are
not import locations. This reports CPython's target import time, not total
process startup time. For a less noisy observation, use repeated sampling:

```python
from importtime_check import sample_import

result = sample_import("json", warmups=1, samples=5)
print(result.median_cumulative_us)  # upper median, integer microseconds
print([run.target_event.cumulative_us for run in result.samples])
```

Each warmup and sample uses a fresh child process. Warmups are preserved but
excluded from the median. This reduces single-run noise; it does not guarantee
that two machines or CI runs have comparable timings. Regression checks are
still planned.

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
