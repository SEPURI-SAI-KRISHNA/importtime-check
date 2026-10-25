# 0012: Report-to-baseline proposals remain unapproved policy

- Status: Accepted when the pull request containing this record merges
- Decision date: 2026-10-25
- Decision issue: [#83](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/83)
- Milestone: [0.2.0a2](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/milestone/6)
- Extends: [0007](0007-regression-and-integration-contract.md),
  [0009](0009-per-target-baseline-budgets.md), and
  [0011](0011-offline-report-cohorts.md)
- Implementation issues: [#85](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/85),
  [#87](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/87),
  [#89](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/89),
  [#91](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/91), and
  [#92](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/92)
- Owners: `importtime-check` maintainers

## Context and trust boundary

ADR 0011 can strictly load version-1 measurement reports and summarize 2–64
caller-asserted comparable runs. A cohort's observed median of run medians
is useful evidence, but it is not an approved CI threshold. Report files
contain only four safe interpreter fields; they omit the baseline `profile`,
dependency lock, Python patch level, full runner image, hardware, and load.
Their SHA-256 digests identify bytes, not independent runs or equivalent
environments. Runner and installation context labels are caller assertions,
not attestations.

A schema-1 baseline is different: it is reviewed policy consumed by `check`
and the optional pytest gate. Its per-target absolute and relative allowances
are choices a human must make. The proposal feature may help construct a
*candidate* from observations, but must never promote the candidate into the
committed baseline, select budgets, or claim statistical comparability.
Once deliberately supplied to `check`, a candidate is technically a valid
baseline; approval is therefore a repository review and CI path boundary,
not a bit that schema 1 can enforce.

## Decision

### Candidate value and required inputs

Add `propose_baseline(cohort: CohortSummary, *, profile: str,
per_target_allowances: Mapping[str, TargetAllowance]) -> Baseline` as an
offline, side-effect-free Python API. Require an actual validated
`CohortSummary` value, not a loose analysis JSON dictionary, report path,
single measurement, or `CohortComparison`. The normal path builds the
summary from complete reports using ADR 0011's
`summarize_measurement_reports`, with explicit `runner_context` and
`install_context`. Accepting a programmatically constructed summary does
not certify that its claimed source digests came from independent runs;
callers retain that responsibility.

The candidate's `environment.implementation`, `python`, `platform`, and
`machine` come **only** from the cohort's validated four-field identity.
The caller must deliberately supply a non-blank `profile` under the existing
schema-1 validation rule; neither context label is silently copied into it.
The caller must review that the reported identity, selected profile, actual
runner, and dependency lock describe the environment where the baseline
will be used. No interpreter probe or target import occurs during proposal.
The cohort's `sampling` is copied unchanged. For each sorted target,
`baseline_cumulative_us` is exactly its `observed_median_us`, the upper
median of complete-run upper medians; neither the minimum, maximum, pooled
child samples, nor a before/after delta seeds it.

Require a non-empty mapping with **exactly one** `TargetAllowance` for every
cohort target and no other keys. Each allowance has an explicit non-boolean,
non-negative integer `max_increase_us` and an ordinary non-negative decimal
string `max_increase_percent`, using ADR 0009's validation and normalization.
Zero is an explicit allowance. There is no default, common budget, inherited
approved-budget mode, interpolation from spread, or automatic recommendation.
The CLI must reject duplicate named budgets *before* turning them into a
mapping, even when duplicate values agree. Missing, extra, invalid, mixed,
or ambiguous inputs reject the whole proposal with sorted target details;
there is no partially constructed `Baseline`.

The result is the existing immutable `Baseline` with `schema_version: 1`.
Encoding uses the existing canonical schema-1 writer and exact root,
environment, sampling, and target keys. No `candidate`, approval state,
report digest, context label, range, or explanation field is added to the
policy JSON. A deliberate save/load round trip must retain the same policy
values, and existing `check` and pytest readers must consume a separately
approved file without migration or changed threshold math.

### Two-target worked example

Use ADR 0011's two complete `build-before` reports on asserted runner
`ubuntu24-py311`. Both say `cpython 3.11`, `linux/x86_64`, one warmup and
three recorded samples. Their run medians are `email: 10, 11 us` and
`json: 42, 41 us`; the cohort's observed upper medians are `11` and `42 us`,
with spread `1 us` for each. After inspecting the runner definition and
dependency lock, a reviewer explicitly chooses profile `ci-locked-v1` and
*distinct* allowances: `email=3,15` and `json=8,10` (microseconds, percent).
The candidate's complete policy shape is:

```json
{
  "environment": {
    "implementation": "cpython",
    "machine": "x86_64",
    "platform": "linux",
    "profile": "ci-locked-v1",
    "python": "3.11"
  },
  "sampling": {
    "samples": 3,
    "statistic": "upper_median",
    "warmups": 1
  },
  "schema_version": 1,
  "targets": {
    "email": {
      "baseline_cumulative_us": 11,
      "max_increase_percent": "15",
      "max_increase_us": 3
    },
    "json": {
      "baseline_cumulative_us": 42,
      "max_increase_percent": "10",
      "max_increase_us": 8
    }
  }
}
```

The example numbers illustrate data flow, not recommended budgets. A
reviewer may reject the proposal because two close observations do not
establish a stable normal. The existing schema-1 rule still treats an
increase as a regression only if it exceeds **both** allowances for that
target; this feature does not change the rule.

### Separate evidence and explanation

Keep review evidence outside the baseline schema, in a companion review
record or PR description. For each proposal, make available the source
report SHA-256 digests in deterministic order, report count, safe four-field
identity, sampling, asserted runner and installation contexts, per-target
run medians/range/spread, proposed median, explicit profile and allowances,
and the exact candidate-file digest. The human review also records the
runner definition, Python patch level, dependency lock, installed revision,
and rationale for each budget; the tool cannot infer or certify those facts.
An optional comparison to an explicitly supplied existing schema-1 baseline
names changed identity, sampling, target-set, median, and allowance fields.
It never imports old allowances or modifies either policy file. Invalid or
unsupported old policy fails closed rather than producing a partial diff.

Issue #89 owns deterministic API/CLI explanation. It may render text or a
separately versioned review artifact, but it must not put proposal metadata
into schema 1. Normal diagnostics and generated review output omit full
private paths, raw report contents, subprocess output, and secrets; source
digests and deliberately supplied safe context labels are sufficient to
identify inputs for review. A digest alone never proves report origin.

### CLI and file boundary

Issue #87 adds `baseline propose` with repeated `--file PATH`, required
`--runner-context`, `--install-context`, `--profile`, one repeated
`--budget MODULE=US,PERCENT` per cohort target, and `--output PATH`.
It loads all reports with ADR 0011's bounded reader, validates the complete
cohort and every proposal input, then writes canonical schema-1 bytes to
one **new** destination. It does not accept `--replace`, common-budget
flags, an implicit profile, stdin, URLs, globs, target imports, or network
input. It does not guess budgets from spread or an old baseline.

An existing destination of any kind, including a file, directory, or
symlink, is a conflict. Use the established create-only atomic save path;
never truncate or replace existing bytes and do not create a partial
candidate on failure. A successful command prints a concise review
reminder, not an approval or regression verdict. Expected report,
comparability, proposal, and I/O failures exit `2` with empty stdout and
safe stderr. CLI syntax errors retain parser exit `2`; interruption is not
reported as a completed proposal. The builder raises a new
`BaselineProposalError(ValueError)` with `kind: "proposal-invalid"` for a
wrong cohort type, invalid profile, or missing, extra, or invalid budgets.
Its sorted `missing` and `unknown` target tuples are populated for a budget
set mismatch. Existing `MeasurementReportError` and `BaselineError` still
identify upstream report/cohort and file failures respectively; ordinary
messages must not disclose private paths or raw input. This does not change
published `record`, `refresh`, `check`, or pytest error behavior.

### Approval and CI ownership

The consuming project's manual candidate workflow may collect comparable
reports and upload the candidate plus separate explanation for a human to
inspect. It must not commit, replace, or point the required PR gate at the
candidate automatically. A separate reviewed PR deliberately copies or
commits the chosen schema-1 policy to the approved baseline path; only then
may the existing `check`/pytest gate consume it. The workflow must preserve
the old approved baseline and gate behavior when proposal creation fails.
The new feature does not change `release.yml`, grant a CI write token, or
upload report data by itself.

## Validation and ownership

- Issue #85 tests fixed 2–64-report cohort input, exact sorted target and
  budget matching, profile choice, zero/fractional allowances, canonical
  schema-1 round trip, immutable returned value, and unchanged `check`
  boundaries. Reject a single report, fabricated wrong types, mismatched
  identity/sampling/targets, duplicate report bytes, and malformed budgets
  without side effects or partial values.
- Issue #87 tests complete CLI options, duplicate/missing/extra/mixed
  budgets, malformed or future reports, non-comparable cohorts, existing
  output file/directory/symlink, an invalid *later* input, and interruption.
  Failed commands leave existing bytes unchanged and create no candidate;
  installed-wheel smoke exercises the happy and fail-closed paths.
- Issue #89 tests deterministic provenance/explanation and optional
  field-level diff, with private-path redaction, invalid old policy, and no
  hidden schema-1 fields. Issue #91 tests a manually triggered, pinned
  consuming-project example and CI guardrails against auto-commit or
  candidate-as-gate paths. Issue #92 tests/document-checks a two-target
  walkthrough from reports to candidate to separate approval PR.
- Maintainers retain Ruff, strict mypy, 100% package branch coverage,
  artifact validation, clean-wheel smoke, supported-Python/OS CI, and
  existing archived report/baseline compatibility checks. No test uses
  wall-clock timing to approve a budget.

## Compatibility and migration

This is additive in an alpha release. Version-1 measurement reports,
version-1 analysis documents, and schema-1 baselines keep their exact
meanings. Existing `record`, `refresh`, `check`, pytest configuration,
threshold arithmetic, and exit codes do not change. A candidate needs no
format migration to become an approved baseline, but **does** require
separate human review and a deliberate path change in version control.
Older approved baselines are never rewritten by proposal generation.

## Alternatives, risks, and rollback

Copying one report ignores run-to-run variation. Pooling child samples
overweights reports and changes ADR 0011's statistic. Automatically using
spread or old allowances as a budget would make unreviewed policy choices.
Embedding provenance or a `candidate` flag in schema 1 would either break
strict readers or create a false technical approval signal. Reusing
`baseline record` would launch new measurements instead of using the
reviewed report set. Direct CI write-back is rejected because it bypasses
the baseline PR review boundary.

Even a valid cohort can be noisy, selectively sampled, or mislabeled;
multiple reports, source hashes, ranges, and explicit contexts improve
reviewability but cannot prove causation or statistical stability. The
design-only PR can be revised before implementation. After APIs and CLI
ship, a material contract change needs a new design issue, compatibility
review, and where applicable a new format/version rather than silently
reinterpreting existing policy.
