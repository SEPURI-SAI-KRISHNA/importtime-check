# 0011: Offline measurement report cohorts

- Status: Accepted when the pull request containing this record merges
- Decision date: 2026-10-16
- Decision issue: [#80](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/80)
- Milestone: [0.2.0a1](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/milestone/5)
- Extends: [0010](0010-multi-target-measurement-reports.md)
- Implementation issues: [#82](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/82),
  [#84](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/84),
  [#86](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/86),
  [#88](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/88), and
  [#90](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/90)
- Owners: `importtime-check` maintainers

## Context

ADR 0010 publishes a version-1 JSON *measurement* report containing four
safe interpreter fields, sampling settings, and ordered timings for each
target. It has no decoder or cohort API. Users can collect several artifacts,
but must manually check their shapes and calculate variation. Baseline schema
1 is separately reviewed regression policy; it must not become a container
for exploratory observations.

The four reported environment fields omit Python patch level, dependency
versions, runner image, hardware details, host load, and the import side
effects of targets. Matching fields therefore cannot prove that separate
runs were comparable. This decision supports offline, descriptive analysis
with an explicit caller assertion of controlled context. It does not make a
statistical or policy judgment.

## Decision

### Strict version-1 input and immutable values

Export `decode_measurement_report(raw: bytes | str) -> MeasurementReport` and
`load_measurement_report(path: str | os.PathLike[str]) -> MeasurementReport`.
They do not import targets, launch Python, write files, or use the network.
`load_measurement_report` accepts one existing regular, non-symlink file and
reads at most 2 MiB plus one byte to detect an oversized file. The decoder
applies the same 2 MiB UTF-8 byte limit to direct bytes or strings. Invalid
UTF-8, duplicate JSON keys, non-finite constants, malformed JSON, and
unsupported `report_version` values fail closed. File ordering, whitespace,
and JSON object-key order need not be canonical; semantic fields must be.

The only accepted root keys are `environment`, `report_type`,
`report_version`, `sampling`, and `targets`. Require `report_type` to be the
string `measurement` and `report_version` to be the non-boolean integer `1`.
Accept no baseline, check, analysis, or future-version document as a v1
measurement. Validate exact nested keys:

| Object | Required keys |
| --- | --- |
| `environment` | `implementation`, `machine`, `platform`, `python` |
| `sampling` | `samples`, `statistic`, `warmups` |
| each target | `samples_us`, `upper_median_us`, `warmups_us` |

Use ADR 0010's meanings and the existing `EnvironmentIdentity` validation:
`implementation` is `cpython`; `python` is a major.minor string; `platform`
and `machine` are non-blank strings, with `machine` normalized to lower case
after trimming. `statistic` is `upper_median`. `profile` is not a report
field. Target keys are distinct valid dotted module names, and there are
1–128 targets. `warmups` is a non-boolean integer in 0–100, `samples` a
non-boolean integer in 1–1000. Every target has exactly that many ordered
warmup and sample values. Each timing and `upper_median_us` is a non-boolean
integer in 0–2^63−1 microseconds. Recalculate the upper median by sorting
only recorded samples and choosing index `len(samples) // 2`; reject a
declared median that differs. These reader limits are analysis limits, not a
retroactive change to what the 0.1.0a4 emitter can produce. Oversized but
otherwise valid reports require a separately reviewed limit change.

`MeasurementReport`, `ReportIdentity`, and `ReportTarget` are frozen, slotted
values with copied tuples and an immutable, module-sorted target mapping.
The report contains its four-field identity, sampling policy, target values,
version 1,
and a `source_sha256` of the exact UTF-8 input bytes. For a string input,
hash its UTF-8 encoding. A digest identifies supplied bytes for review; it
does **not** prove independent measurement or environmental comparability.
No path, executable, working directory, raw stderr, or dependency list is
added to the report model. An input with extra fields is rejected rather
than silently reinterpreted.

### A cohort is an asserted controlled set

Export `summarize_measurement_reports(reports: Sequence[MeasurementReport],
*, runner_context: str, install_context: str) -> CohortSummary`. Require 2–64
reports, not a string or bytes sequence, with distinct `source_sha256` values.
The caller must attest that all reports in one cohort came from a controlled
runner class and one intended installed dependency/revision state. Both
context identifiers are case-sensitive ASCII labels matching
`[A-Za-z0-9][A-Za-z0-9._-]{0,127}`; they are descriptive assertions, not
verified hashes, and must not contain paths or secrets. The CLI makes the
same two values explicit options. The caller should retain its lockfile,
runner definition, and revisions alongside artifacts; the v1 report alone
cannot validate them.

All cohort reports must have exactly the same four safe environment fields,
sampling policy, and target set. Compare the validated values, not JSON
formatting or input order. A mismatch rejects the entire cohort with sorted
field names; there is no partial summary. For each target, take each
report's `upper_median_us` as one run observation. Sort those observations
and choose the upper median at index `len(reports) // 2` as
`observed_median_us`. Also expose `min_us`, `max_us`, and
`spread_us = max_us - min_us`. This is a median of complete-run medians, not
a pooled median of all child samples. It remains an *observed* integer even
with an even number of reports. Warmups never contribute.

The immutable `CohortSummary` carries the safe identity, sampling, both
context identifiers, report count, source digests sorted lexicographically,
and target summaries sorted by module. Each target's `run_medians_us` tuple
follows that digest order, retaining provenance without private file paths.
Changing input-file order must not change the result or its rendering.
Duplicate exact bytes fail rather than silently double-weighting one
artifact; differently serialized duplicate observations cannot establish
independence and remain the reviewer's responsibility.

### Before/after comparison has no verdict

Export `compare_report_cohorts(before: CohortSummary,
after: CohortSummary) -> CohortComparison`. Each input was validated as a
cohort first. Require the same target set, four-field identity, sampling
policy, and `runner_context` across sides. The two `install_context` labels
may differ because the intended code or dependency change is what is being
examined; retain both and require the reviewer to explain the change. A
different runner class, Python major.minor, architecture, target set, or
sampling policy is not normalized into a comparison. Nor can equal labels
prove that the unrecorded runner properties truly match.

For each target, report `before_us` and `after_us` as the two cohort
`observed_median_us` values, `change_us = after_us - before_us`, and each
side's range and spread. `change_percent` is a signed decimal string with
two fractional digits representing `100 * change_us / before_us`, rounded
half-up using integer arithmetic rather than binary floating point. A
positive nonzero value has `+`, a negative nonzero value has `-`, and a
rounded zero is `0.00`. If `before_us` is zero, `change_percent` is JSON
`null` and text says `n/a`, even if both sides are zero. Keep the exact
signed microsecond delta visible when percentage rounding hides a small
change. The result has no pass/fail field, allowance, confidence interval,
p-value, outlier deletion, or automatic budget recommendation.

### Versioned presentation and failure behavior

Add `report summarize` with repeated `--file PATH`, required
`--runner-context` and `--install-context`, and `--format text|json`
(default text). Add `report compare` with repeated `--before-file PATH` and
`--after-file PATH`, one required shared `--runner-context`, required
`--before-install-context` and `--after-install-context`, and the same
format option. Every side needs at least two complete reports. No globbing,
stdin, URL fetch, file output, target import, or report rewrite is implied.
Validate every file and all comparability conditions before writing a byte
to stdout. Successful commands exit `0`; expected input/read/comparability
failure exits `2` with concise stderr and empty stdout. They never emit the
`check` command's regression exit code `1`. `--debug` retains normal
traceback behavior; normal diagnostics identify an input by one-based
argument position and a safe error kind, not raw JSON, stderr, or full
private paths.

JSON summaries use sorted object keys, two-space indentation, and one
trailing newline. They have `analysis_type: "cohort_summary"` and
`analysis_version: 1`, distinct from both measurement `report_version: 1`
and baseline `schema_version: 1`. The remaining exact root keys are
`environment`, `sampling`, `runner_context`, `install_context`,
`report_count`, `sources_sha256`, and `targets`. Environment and sampling
have the v1 report field shapes. `sources_sha256` is the sorted digest array;
each target object has `run_medians_us` in that same order plus
`observed_median_us`, `min_us`, `max_us`, and `spread_us`. A comparison has
`analysis_type: "cohort_comparison"`, `analysis_version: 1`, complete
`before` and `after` summary objects in that shape, and a module-sorted
`changes` mapping. Each change contains `before_us`, `after_us`,
`change_us`, and `change_percent` (string or null). New incompatible
analysis fields or meanings require a new `analysis_version` and migration
guidance; neither existing report nor baseline versions change.

Text summary starts with report count and the two caller-declared contexts,
then safe identity and sampling, then one line per sorted target showing
observed median, range, and spread. Text comparison starts with before/after
counts and contexts, then one line per sorted target showing signed change
and both spreads. It explicitly says `Descriptive only; no regression
verdict.` No timing-dependent value is promised to be stable between actual
runs; presentation is deterministic for identical validated inputs.

Use one `MeasurementReportError(ValueError)` family with stable `kind` values
`report-missing`, `io-error`, `report-limit`, `report-invalid`,
`report-unsupported`, `context-invalid`, `cohort-invalid`, and
`cohort-mismatch`. A cohort failure may carry sorted `differing_fields`
and a one-based `source_index`; ordinary messages do not contain raw
content or private paths. An unsupported future version is not interpreted
as v1. No API function returns a partially valid value on failure.

## Worked examples

Assume all reports have `cpython 3.11` on `linux/x86_64`, one warmup, three
recorded samples, and the two targets `email` and `json`. The caller
declares `runner_context=ubuntu24-py311` and
`install_context=build-before` for these two complete reports:

| Report | `email` samples / upper median | `json` samples / upper median |
| --- | --- | --- |
| A | `8, 10, 12` / `10` | `40, 42, 44` / `42` |
| B | `9, 11, 13` / `11` | `39, 41, 43` / `41` |

The before cohort has `email` observed median `11`, range `10..11`, spread
`1` microsecond; `json` observed median `42`, range `41..42`, spread `1`.
Even with only two reports, the upper choice is an actual run median. If B
instead declares four recorded samples while A declares three, the cohort
fails with `cohort-mismatch` on `sampling.samples` and no summary is emitted.

Two after reports C and D use the same runner context but
`install_context=build-after`:

| Report | `email` samples / upper median | `json` samples / upper median |
| --- | --- | --- |
| C | `12, 14, 16` / `14` | `45, 47, 49` / `47` |
| D | `13, 15, 17` / `15` | `46, 48, 50` / `48` |

The after cohort's observed medians are `15` and `48`, each with spread
`1`. The comparison reports `email: +4 us, +36.36%` and `json: +6 us,
+14.29%` alongside both ranges. This is an observed shift, **not** a
regression verdict or evidence that host noise was controlled. A side with
an observed median of zero has an undefined percentage, not infinity.

## Ownership and validation

- Issue #82 owns bounded file and direct-byte decoding, exact schema checks,
  immutable values, digest provenance, safe errors, and archived v1 fixtures.
- Issue #84 owns cohort validation and observed summaries; #88 owns
  before/after comparison. Their tests use fixed integers, shuffled inputs,
  duplicate bytes, zero denominators, and mismatch cases, not real-time
  thresholds.
- Issues #86 and #90 own the CLI commands, deterministic text and JSON,
  no-partial-stdout behavior, and operational exit codes. Existing
  `measure`, `check`, and `baseline` commands keep their published output.
- Issue #93 keeps archived compatible and incompatible artifacts in CI;
  #95 exercises installed-wheel report paths on selected Windows and macOS
  lanes while preserving the required CI aggregate and existing matrix.
  Issue #97 documents collection, context assertions, variance, and review
  without making an observation-only CI artifact a required gate.

The usual Ruff, strict mypy, full tests with 100% package branch coverage,
artifact inspection, clean-wheel smoke, DCO, and security checks remain in
force. The Python API must reject invalid values without side effects; CLI
tests must show a malformed later file leaves stdout empty. Fixed fixture
values test arithmetic, while bounded real-child tests establish packaged
integration without asserting wall-clock thresholds.

## Compatibility and migration

This is additive to the alpha API. It does not rewrite v1 measurement JSON,
introduce fields into schema-1 baselines, reinterpret existing check reports,
change one-target measure text, alter check exit codes, or change pytest
integration. Existing artifacts need no migration when they meet the
documented reader limits. New analysis JSON is independently versioned.
Future report changes must use a new `report_version` with an explicit
decoder/migration decision; silently accepting unknown fields is not a
compatibility strategy.

## Alternatives considered

Permissive dictionaries or pooling all child samples would hide malformed
reports and overweight files with more samples. A statistical significance
claim is not justified by a few noisy runs. Treating the comparison as a
baseline gate would let observations acquire unreviewed policy authority.
A dashboard or hosted artifact store adds operational and privacy costs
without being needed for offline review. The explicit context labels are
weaker than a recorded dependency lock, but v1 cannot be retrofitted with
new fields; callers must retain that evidence separately.

## Consequences and follow-up

Each report file can be read and inspected offline without launching the
target or changing approved policy. A useful review now needs at least two
complete reports per side plus separately retained runner and installation
context. The cohort result can inform, but never replace, the later human
choice of baseline allowances. Issues #82–#97 implement and document the
separate layers described above.

## Risks and rollback

Reading archived artifacts has resource and trust risks. Byte, target,
sample, and cohort limits bound normal use, exact keys reject silent format
drift, and duplicate digests prevent a trivial repeated-input mistake. The
design-only PR can be revised before implementation. Once analysis JSON or
APIs ship, incompatible behavior needs a new design issue, version, and
migration guidance rather than an in-place reinterpretation.

## Primary contracts

- [ADR 0006: isolated measurement and sampling](0006-isolated-measurement-and-sampling.md)
- [ADR 0007: reviewed baseline and regression decisions](0007-regression-and-integration-contract.md)
- [ADR 0010: multi-target measurement reports](0010-multi-target-measurement-reports.md)
