# 0010: Multi-target measurement reports

- Status: Accepted when the pull request containing this record merges
- Decision date: 2026-10-14
- Decision issue: [#68](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/68)
- Implementation issues: [#69](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/69)
  and [#70](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/70)
- Documentation follow-up: [#71](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/71)
- Extends: [0006](0006-isolated-measurement-and-sampling.md) and the
  measurement CLI introduced by [#26](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/26)
- Owners: `importtime-check` maintainers

## Context

ADR 0006 defines one isolated import observation and repeated samples of one
installed module. The published `measure --module MODULE` command displays
one module's warmups, recorded samples, and observed upper median as text.
Baseline record and check already accept several modules, but a baseline is
reviewed regression policy with allowances; it is not a neutral place to
collect exploratory measurements. Running `measure` separately for each
module leaves users to validate target sets and assemble an artifact.

This decision adds a standalone, multi-target observation path. It does not
change what CPython's `-X importtime` measures, turn observations into a
performance verdict, or make timings from unlike environments comparable.

## Decision

### Batch sampling is an additive Python API

Export `sample_imports(modules: Sequence[str], *, python_executable=None,
timeout_seconds=30.0, working_directory=None, warmups=1, samples=5)
-> tuple[ImportSampleSet, ...]` from `importtime_check`. The returned tuple is
sorted by exact module name; every `ImportSampleSet` is the existing frozen,
slotted value from ADR 0006. No new public batch model is needed. For example:

```python
from importtime_check import sample_imports

for result in sample_imports(("email", "json"), warmups=1, samples=5):
    print(result.module, result.median_cumulative_us)
```

The input must be a non-empty sequence of distinct valid dotted-module
names. A string or bytes object is not a module sequence. Validate the entire
selection, sample counts, interpreter, timeout, and working directory before
launching any target child. Duplicate selections fail even when identical.
Sort targets lexicographically rather than preserving caller order, so an
explicit target set has one report order. Existing module-name validation
and `sample_import` defaults apply unchanged.

Resolve the interpreter, timeout, and working directory once and snapshot
the caller's environment once for the batch. Run targets sequentially in
sorted order. Each warmup and recorded sample still uses its own fresh
isolated child, with the same selected runtime context and per-child timeout.
Warmups stay excluded from each target's observed upper median. Do not retry
failed runs or run targets concurrently: overlapping imports would add
contention to a timing tool.

Return the complete tuple only after every target succeeds. On a failed
target, propagate its `ImportMeasurementError` with the exact module,
`run_phase`, and one-based `run_number`; no partial tuple is returned. A
caller can still inspect the exception as ADR 0006 permits, but successful
earlier targets are not exposed as a successful batch. `sample_import` and
`measure_import` retain their published signatures and behavior.

### `measure` supports several modules and JSON

Accept one or more repeated `--module MODULE` options and add
`--format text|json` (default `text`) to `measure`. Validate the full target
list and sampling/runtime options before probing or importing. The command
delegates batch sampling to `sample_imports`; it does not create, refresh, or
read a baseline. For example:

```console
importtime-check measure --module email --module json --warmups 1 --samples 5 --format json
```

Omit `--format json` for a human-readable two-module report:

```console
importtime-check measure --module email --module json --warmups 1 --samples 5
```

The existing one-module text invocation, including its lines, order, and
newline behavior, remains byte-for-byte compatible. For multiple modules,
text repeats that three-line block in sorted target order, without adding a
policy verdict. A repeated name is an error, not a request to sample the
same module twice. Previously repeated `--module` values had no documented
meaning for `measure`; this defines them without changing valid old calls.

### JSON is a measurement report, not baseline schema 1

The successful JSON document has this separate, versioned shape; values
below illustrate structure, not expected timings:

```json
{
  "environment": {
    "implementation": "cpython",
    "machine": "x86_64",
    "platform": "linux",
    "python": "3.11"
  },
  "report_type": "measurement",
  "report_version": 1,
  "sampling": {
    "samples": 2,
    "statistic": "upper_median",
    "warmups": 1
  },
  "targets": {
    "email": {
      "samples_us": [280, 300],
      "upper_median_us": 300,
      "warmups_us": [310]
    },
    "json": {
      "samples_us": [4100, 4200],
      "upper_median_us": 4200,
      "warmups_us": [4300]
    }
  }
}
```

In JSON mode only, the CLI probes the selected interpreter for the four safe
environment fields shown above using the existing isolated environment
probe. Text mode does not add a probe, preserving the published one-module
path. The JSON probe is additional setup work, not a warmup or recorded
sample. It uses the same selected interpreter, timeout, and working directory
as sampling. The report does not include the executable path, current
directory, full Python patch
version, process environment, raw child stderr, timestamps, budgets, baseline
medians, or regression status. There is no `profile`: users may label an
artifact, but that label alone cannot establish comparability.

Each timing is the target's CPython cumulative import microseconds, as an
integer. Warmup and sample arrays preserve execution order; the upper median
uses ADR 0006's observed-value rule. The target mapping is sorted by module
name. Render JSON with sorted object keys, two-space indentation, and one
trailing newline. For identical metadata and observations, output bytes are
identical; measured numbers themselves can vary between runs. This
`report_version` is independent of baseline and check `schema_version: 1`.
Any incompatible future report change requires a new version and documented
consumer migration; no decoder or report-to-baseline conversion is added now.

### Output and failure behavior

Complete all validation, JSON-only interpreter probing, and target sampling
before writing to stdout in either format. A later-target failure must not print a
partial JSON document or misleading partial text report. Expected invalid
input, probe failure, or measurement failure exits with code `2` and concise
stderr, matching the current `measure` failure category; stdout remains
empty. Argument-syntax errors remain CLI usage errors. `--debug` retains its
existing traceback behavior. A successful report exits `0`; `measure` never
returns regression exit code `1`. Do not include private paths or raw child
stderr in ordinary output. Shell redirection may create an empty file on a
failed command; examples must check the exit code before keeping an artifact.

## Ownership boundaries

- The batch API owns complete target validation, one captured import runtime
  context, sequential fresh-process execution, and all-or-nothing return.
- ADR 0006's single-target parser, measurement, sample model, and upper
  median remain the source of truth for each target's observations.
- The CLI owns option parsing, the additional safe interpreter probe,
  presentation, versioned JSON shape, and stdout/stderr discipline.
- Baseline record/check, schema-1 serialization, and the optional pytest
  adapter do not consume or rewrite measurement reports.

## Validation and failure semantics

Issue #69 tests empty, string, duplicate, invalid, and non-sequence target
inputs; validation before child launch; sorted output; shared runtime and
environment snapshot; exact per-target warmup/sample ordering and medians;
later-target failure with its module and run index; and immutable results.
Use deterministic fake children for failure and ordering tests, plus bounded
real-child integration tests without timing-value assertions.

Issue #70 tests one-module text compatibility, sorted multi-module text,
canonical JSON fields and bytes for fixed observations, safe metadata,
stdout-empty failures, exit codes, interpreter-probe failure, and a
two-module installed-wheel path on the supported Python matrix. Ruff,
strict mypy, full tests with 100% package branch coverage, build, artifact,
and clean-wheel gates remain required.

## Compatibility and migration

This is additive to the alpha API and CLI. Existing `sample_import`,
`measure_import`, one-module `measure` text output, baseline schema 1,
`check` text/JSON, and pytest behavior stay usable. No existing file needs
migration. A measurement report is observational evidence only: it carries
neither approved allowances nor a comparable-run guarantee. Consumers that
choose to parse the new JSON should check `report_type` and `report_version`
rather than treating it as a baseline or check report.

## Alternatives considered

Multiple one-target commands require custom aggregation and can use
different runtime settings. Reusing `baseline record` would require invented
budgets and risk committing unreviewed policy. Reusing baseline or check JSON
would blur observations and verdicts. A separate JSON format keeps the
meaning explicit. Parallel sampling could reduce elapsed time but introduce
cross-target contention; the first batch contract remains sequential. A
public batch wrapper class would duplicate the existing immutable sample
sets without a demonstrated need, so the API returns a tuple.

## Consequences and follow-up

- Issue #69 implements `sample_imports` and exports it from the package.
- Issue #70 adds repeated `--module`, multi-target text, and versioned JSON
  to `measure`, while preserving one-module text output.
- Issue #71 documents reviewable reports and a pinned consuming-project CI
  artifact example. The example must not automatically update a baseline.
- Collecting several targets costs one probe plus each target's sequential
  warmups and samples. Host load, dependencies, and interpreter configuration
  still affect numbers; users must establish comparability before choosing
reviewed budgets.

## Risks and rollback

Users may treat sample variation as a confidence interval, or copy observed
medians into CI policy without reviewing comparable runs. Documentation must
label the report as evidence only and keep the baseline-review workflow
separate. The design-only PR can change before implementation; after a
published report format or API is used, incompatible changes need a new
versioned report contract and an explicit migration path, not a silent
reinterpretation of version 1.

## Primary contracts

- [ADR 0006: isolated measurement and upper-median sampling](0006-isolated-measurement-and-sampling.md)
- [ADR 0007: reviewed baseline and regression contract](0007-regression-and-integration-contract.md)
- [Issue #26: original CLI and diagnostic reports](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/26)
