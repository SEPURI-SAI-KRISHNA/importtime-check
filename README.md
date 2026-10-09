# importtime-check

[![CI](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/actions/workflows/ci.yml/badge.svg)](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/actions/workflows/ci.yml)

`importtime-check` is a CI gate for detecting regressions in Python import
time. It measures imports in clean subprocesses, compares results with
deterministic baselines, and reports actionable diagnostics when startup
performance regresses.

## Project status

This project is in early alpha development; its public API is not yet a stable
compatibility commitment.

Version `0.1.0a1` is the first public alpha. Install it with:

```console
python -m pip install --pre importtime-check==0.1.0a1
```

CPython 3.11 through 3.14 are tested. Package metadata requires Python 3.11
or newer; newer interpreter versions are not yet in the tested support matrix.
The core install has no runtime dependencies. Pytest is available only through
the optional `pytest` extra.

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

This API remains an alpha API and may change before the first stable release.

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
that two machines or CI runs have comparable timings.

The library also supports reviewable baselines and exact regression decisions:

```python
from importtime_check import (
    check_baseline,
    probe_environment,
    record_baseline,
    sample_import,
    save_baseline,
)

baseline = record_baseline(
    {"json": sample_import("json")},
    probe_environment(),
    max_increase_us=25,
    max_increase_percent="10",
)
save_baseline("importtime-baseline.json", baseline)
report = check_baseline(baseline)
print(report.status)  # "pass" or "regression"
```

Baselines are versioned JSON and require the same Python minor version,
platform, machine, and profile at check time. Review baseline changes before
using them as CI policy; matching identity does not eliminate host noise.

The installed command supports measuring, recording, inspecting, and checking:

```console
importtime-check measure --module json
importtime-check baseline record --output importtime-baseline.json --module json --max-increase-us 25 --max-increase-percent 10
importtime-check baseline show --file importtime-baseline.json
importtime-check check --baseline importtime-baseline.json
importtime-check check --baseline importtime-baseline.json --format json
```

On the development branch (planned for `0.1.0a2`, **not** available in the
published `0.1.0a1`), refresh the recorded medians after an intentional change:

```console
importtime-check baseline refresh --file importtime-baseline.json --replace
```

Refresh measures the baseline's existing targets with its stored sampling
policy and retains each target's approved allowances. It rejects a different
Python minor version, platform, machine, or profile; changing those or the
target set requires a deliberately re-recorded and reviewed baseline. Review
the resulting file diff before accepting it in CI. Refresh never runs from
`check` or the pytest plugin. Library callers can use
`refresh_baseline(baseline, observations, environment)` to obtain a new
`Baseline` without writing a file; saving it still requires an explicit
`save_baseline(..., replace=True)` call.

`check` exits `0` when all targets pass, `1` for a regression, and `2` for
invalid input or an operational failure. Its JSON output is a stable schema-1
document on standard output, including for exit codes `1` and `2` (except
command-line syntax errors).

If `check` reports an environment mismatch, compare the named fields with the
interpreter, CI runner, and `--profile` used to record the baseline. Only Python
major.minor values are shown; platform, machine, and profile values are not
echoed in the error. If the target set differs, check explicit `--module`
selections against the recorded modules. Correct a selection mistake or record
and review a new baseline for an intentional identity or target-set change;
`refresh` cannot make those policy changes. A matching five-field identity does
not prove that dependencies, hardware, or host load are comparable.

Pytest integration is optional and must be explicitly loaded. For a development
checkout, install its extra and run against an approved baseline. After
publication, install `"importtime-check[pytest]==0.1.0a1"` instead of the
editable checkout:

```console
python -m pip install --editable ".[pytest]"
python -m pytest -p importtime_check.pytest_plugin --importtime-baseline importtime-baseline.json
```

The plugin accepts repeated `--importtime-module` flags to assert the exact
target set and `--importtime-python`, `--importtime-timeout-seconds`,
`--importtime-working-directory`, and `--importtime-profile` to select the
runtime. The corresponding `pytest.ini` settings are `importtime_baseline`,
`importtime_modules`, `importtime_python`, `importtime_timeout_seconds`,
`importtime_working_directory`, and `importtime_profile`. Explicit command-line
values replace settings; otherwise the baseline supplies targets and sampling.
Invalid configuration exits pytest with code `4` before tests. After a passing
test session, a regression or measurement error exits with code `1`; an
existing test failure or interruption is preserved without measuring. The
plugin never refreshes baselines and is not loaded automatically.

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

See [CONTRIBUTING.md](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/blob/main/CONTRIBUTING.md)
for the complete contribution workflow and
[SECURITY.md](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/blob/main/SECURITY.md)
for private vulnerability reporting.
The [first alpha release notes](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/blob/main/docs/releases/v0.1.0a1.md) summarize its
capabilities, compatibility, and limitations.

## Current limits

Measurements are sensitive to host load, dependency changes, and interpreter
configuration. Compare results only in controlled environments with reviewed
baselines. The tool reports CPython's import-time diagnostics, not whole-process
startup time, and it does not yet identify the cause of a regression automatically.

## License

Licensed under the Apache License, Version 2.0. See
[LICENSE](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/blob/main/LICENSE)
and [NOTICE](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/blob/main/NOTICE).

This is an independent open-source project. It is not affiliated with or
endorsed by the Apache Software Foundation.
