# 0006: Isolated measurement and sampling contract

- Status: Accepted when the pull request containing this record merges
- Decision date: 2026-10-04
- Decision issue: [#21](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/21)
- Implementation issues: [#22](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/22) and [#23](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/23)
- Owners: `importtime-check` maintainers

## Context

ADR [0005](0005-parser-and-domain-model-contract.md) defines a pure parser for
CPython's numeric `-X importtime` stderr. The package still needs to run a
target and select its timing. A usable CI measurement must also repeat that
operation without importing the target into the caller's process.

CPython reports self and cumulative import time in microseconds. These are
interpreter measurements, not wall-clock process startup time. Its documentation
also warns that import-time output can be broken in multithreaded applications.
The first measurement API must state what it measures, which environment it
uses, and when it refuses to return a number.

## Decision

### One observation

Export `measure_import(module, *, python_executable=None,
timeout_seconds=30.0, working_directory=None) -> ImportMeasurement`.

- `module` is a non-empty dotted Python module name. Each component must be a
  valid, non-keyword identifier. File paths, code strings, and shell commands
  are not accepted.
- `python_executable` defaults to the caller's `sys.executable`. An explicit
  value must identify an absolute executable path; it is never searched through
  a shell or interpolated into Python code.
- `timeout_seconds` is a finite, positive, non-boolean number. It bounds the
  wait for one launched child, including its interpreter startup and target
  import. Operating-system process creation itself may exceed the timeout
  before the child can be interrupted.
- `working_directory` defaults to the caller's current directory captured at
  call time. An explicit value is a directory path. The same directory is used
  for every run in a sample set.

The child receives a fixed argument vector equivalent to:

```text
<python_executable> -I -X importtime -c <fixed importlib snippet> <module>
```

The fixed snippet reads the module from `sys.argv` and calls
`importlib.import_module`; it never evaluates module text as code. The process
has closed stdin, discarded stdout, and captured stderr. The caller's
environment is snapshotted when the operation begins and passed to each child.
Python's `-I` mode ignores Python-specific environment variables, excludes the
current directory and user site packages from the import path, and leaves the
selected interpreter's installed packages available. Targets therefore need
to be installed in that interpreter's accessible environment. Other inherited
environment variables and target side effects can still affect timings; this
is isolation from Python import-path contamination, not a hermetic sandbox.

Captured stderr is decoded as UTF-8 with replacement for invalid bytes, then
passed to `parse_importtime`. The selected target must have exactly one event
whose module name equals the requested name. Its `cumulative_us` is the
observation used for later regression decisions; `self_us` and all parsed
events remain available for diagnosis. A missing or ambiguous target event is
an error, never a zero-duration success.

`ImportMeasurement` is a frozen, slotted public value with `module`,
`python_executable`, `parsed: ImportTimeParseResult`, and
`target_event: ImportTimeEvent`. The target event must belong to `parsed.events`.
Its timing values retain ADR 0005's integer microsecond units and invariants.

### Repeated sampling

Export `sample_import(module, *, python_executable=None,
timeout_seconds=30.0, working_directory=None, warmups=1, samples=5)
-> ImportSampleSet`. It validates all arguments before launching a child.
`warmups` is a non-boolean integer at least zero; `samples` is a non-boolean
integer at least one. There is no implicit retry after a failed run.

The function runs warmups first, then recorded samples, sequentially. Every
run uses a fresh child process, the same resolved interpreter path, working
directory, environment snapshot, and per-run timeout. It preserves successful
warmup and sample `ImportMeasurement` values separately in execution order.

`ImportSampleSet` is a frozen, slotted public value with `module`,
`python_executable`, `warmups: tuple[ImportMeasurement, ...]`,
`samples: tuple[ImportMeasurement, ...]`, and `median_cumulative_us: int`.
Collections are copied to tuples and checked for a common target and
interpreter. The aggregate is the upper median of recorded target cumulative
times: sort the values and choose the element at index `len(samples) // 2`.
It is therefore always an observed integer value, including with an even
sample count. Warmups never enter the aggregate.

This statistic reduces the influence of a single outlier but does not prove a
performance change. Later baseline policy must account for machine and
environment differences rather than treating the median as noise-free.

## Ownership boundaries

- ADR 0005's parser owns text recognition and malformed-line details.
- The single-run layer owns subprocess launch, cleanup, stderr capture, target
  event selection, and one `ImportMeasurement`.
- The sampling layer owns repeated fresh runs, their ordering, and the median.
- Later baseline logic owns comparison and regression verdicts. CLI and pytest
  integrations present those verdicts without duplicating measurement rules.

## Validation and failure semantics

Invalid public arguments raise `ValueError` before any child starts. Runtime
failures raise `ImportMeasurementError`, a public `RuntimeError` subclass with
`module`, `kind`, `python_executable`, `returncode: int | None`, and `stderr`
as captured text (empty when unavailable). Its `kind` is one of `launch`, `timeout`, `exit`,
`parse`, `missing-target`, or `ambiguous-target`. Error messages are concise;
full stderr is available as an attribute and is not automatically printed.
For a parse failure, the original `ImportTimeParseError` remains the exception
cause with its line number and original line.

A nonzero exit takes precedence over parsing partial stderr. A timeout kills
and reaps the direct child before raising; partial output never becomes a
measurement. User interruption also cleans up the direct child and then
propagates the interruption. Descendant processes spawned by the target are
outside this first contract and must not be described as cleaned up.

In `sample_import`, the first failed run aborts the sequence and returns no
partial sample set. Its error additionally exposes `run_phase` (`warmup` or
`sample`) and the one-based `run_number`; both are `None` for a standalone
observation. Expected subprocess failures never produce a
regression verdict.

Deterministic unit tests cover argument validation, argv construction, result
selection, exact error kinds, cleanup, run ordering, warmup exclusion, median
boundaries, and failure index without relying on wall-clock sleeps or timing
values. Bounded integration tests exercise a real installed interpreter on
Windows, macOS, and Linux across the declared Python matrix. The existing
formatting, strict typing, 100% package branch coverage, build, metadata,
artifact, and clean-wheel checks remain required.

## Compatibility and migration

These are new pre-alpha APIs, so no existing users need to migrate. Once
published, the function names, defaults, model fields, units, upper-median
rule, and failure kinds are compatibility promises. A later change to
interpreter isolation or sampling semantics requires a new design decision and
documented migration.

Before first publication, rollback is removal of the unpublished APIs. After
publication, incompatible changes follow the project's versioning policy.

## Alternatives considered

In-process import was rejected because `sys.modules` and other process state
would contaminate repeated runs. Shell command strings and arbitrary code
targets were rejected because quoting and evaluation add avoidable risk.
One observation alone is too sensitive to noise for the planned regression
gate; an adaptive benchmark or external statistics dependency adds complexity
without a demonstrated need. The upper median keeps an integer observation
and avoids interpolating timing values. A fully sanitized environment was
deferred because targets often need legitimate environment configuration.

## Consequences and follow-up

- Issue #22 implements one isolated observation after this ADR merges.
- Issue #23 implements repeated sampling on top of Issue #22.
- Targets installed only in the user site or available only through the
  checkout's import path need installation into the selected interpreter.
- Sampling adds process cost: defaults perform one warmup and five recorded
  imports, each with a 30-second timeout.
- The API cannot promise stable results on shared CI hosts or accurate timing
  for multithreaded import output.
- Baseline formats, thresholds, CLI output, and pytest integration remain
  separate decisions and issues.

## Primary references

- [Python command-line `-I` and `-X importtime` options](https://docs.python.org/3/using/cmdline.html)
- [Python subprocess timeout and cleanup behavior](https://docs.python.org/3/library/subprocess.html)
- [Python `statistics.median_high` behavior](https://docs.python.org/3/library/statistics.html#statistics.median_high)
