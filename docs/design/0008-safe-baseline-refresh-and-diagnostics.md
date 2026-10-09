# 0008: Safe baseline refresh and comparison diagnostics

- Status: Accepted when the pull request containing this record merges
- Decision date: 2026-10-09
- Decision issue: [#40](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/40)
- Implementation issues: [#41](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/41)
  and [#42](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/42)
- Extends: [0007](0007-regression-and-integration-contract.md); replaces only
  its generic environment-mismatch message, not its comparison rules
- Owners: `importtime-check` maintainers

## Context

ADR 0007 makes a schema-1 baseline a reviewed policy file. In `0.1.0a1`,
`baseline record --replace` can update its timings, but it requires common
allowance flags and can erase different per-target allowances. The existing
`check` command refuses non-comparable environments and target sets, correctly,
but its environment error does not identify the differing fields. A safe
maintenance path must not turn either problem into an implicit rebaseline.

## Decision

### Refresh is a narrow, explicit operation

Add `importtime-check baseline refresh --file FILE --replace` with the same
`--python`, `--timeout-seconds`, `--working-directory`, and `--profile` runtime
selectors as `check`. `--replace` is mandatory; omitting it is a command-line
usage error before probing or measuring. `refresh` requires an existing,
readable schema-1 **regular file**. It rejects a symlink path, directory,
missing file, or malformed/unsupported baseline; it never creates one.

The command reads and validates the old file once, retaining its original
bytes for a pre-commit change check. It uses exactly the stored target names,
sorted by module, and exactly the stored warmup/sample counts and upper-median
statistic. There is no `--module`, allowance, or sampling override on refresh.
It probes the selected interpreter before target imports and requires its
five-field identity to equal the stored identity. Then it measures every
target in fresh isolated children as in ADR 0006. A failed probe, target run,
or incomplete sample set aborts the whole refresh; partial results are never
written. `check` and the pytest plugin remain read-only.

The core gains a pure public `refresh_baseline(baseline, observations,
environment) -> Baseline`. It requires exact environment and target-set
equality, the stored sampling counts, and one interpreter across all complete
sample sets. It returns a new schema-1 `Baseline` whose **only** changed values
are `baseline_cumulative_us` for the stored targets. It copies the old
`environment`, `sampling`, each target's `max_increase_us`, and each target's
`max_increase_percent`. It does not evaluate thresholds, change allowances,
or decide that a new timing is acceptable; reviewers own that decision.

Before replacement, the command checks that the file still contains the raw
bytes it originally read and is still a regular, non-symlink file. A detected
external edit fails rather than overwriting it. This is a best-effort guard,
not a cross-process compare-and-swap: callers must not run concurrent writers
against one baseline. The complete new baseline is encoded canonically and
written to a temporary file in the same directory, then committed with one
replacement operation. Validation, measurement, encoding, and temporary-file
write failures caused by this command leave the old bytes untouched. Once
replacement succeeds, the new baseline is committed; cleanup or output
handling must not report a pre-commit failure after that point. Do not fall
back to copy/truncate on a platform where replacement fails. This does not
promise survival of sudden power loss or atomic coordination with another
writer.

On success, text output lists every target in sorted order as its old and new
median in integer microseconds, with a signed difference, followed by a clear
statement that target names, sampling, identity, and allowances were retained.
This is a review aid, not a regression verdict. The resulting canonical JSON
is meant to be reviewed in version control before acceptance in CI. The CLI
returns `0` only after a committed refresh; invalid input, non-comparable
state, measurement failure, or pre-commit I/O failure returns `2`. User
interruption propagates. Missing files use `baseline-missing`; malformed and
unsupported files retain `baseline-invalid` and `schema-unsupported`;
non-regular paths, detected external edits, and write failures use `io-error`.
Identity and target-set failures retain their existing kinds, and child-run
failures retain `ImportMeasurementError`. There is no refresh JSON report in
this release.

### Identity or target changes require a new baseline

Refresh never changes the five identity fields or adds/removes targets. A
different Python minor version, platform, machine, implementation, or profile
fails closed even with `--replace`. A caller supplying observations with
missing or extra targets to the pure API also fails closed. A deliberate
change to identity, target set, sampling, or allowances uses the existing
`baseline record --replace` path (or a separately reviewed edit) and a normal
version-control review. That path is intentionally more work because it
changes the comparison policy. A dependency or host change **within** the
same five-field identity is not detectable automatically; refresh can record
it, but the user must judge whether the environment is genuinely comparable.

### Actionable, privacy-conscious comparison errors

The shared core, not each adapter, identifies mismatches. `BaselineError`
retains its existing `kind`, `reason`, `missing`, and `stale` attributes and
adds a tuple-valued `differing_fields: tuple[str, ...]`, empty except for an
identity mismatch. Field names follow this fixed order: `implementation`,
`python`, `platform`, `machine`, `profile`. `check_baseline` and
`evaluate_baseline` use the same identity-difference helper. The CLI and
pytest consume the resulting error without reimplementing comparisons.

The human-readable reason names every differing field. It may show baseline
and current Python major.minor values, which are already validated numeric
strings. It does **not** echo values for `platform`, `machine`, or `profile`:
the latter is user-supplied and the others need not be safe to reflect from a
hand-edited file or interpreter. It never includes an executable path,
hostname, child stderr, environment variable, or raw arbitrary field value.
For example, `python: baseline 3.11, current 3.12; profile differs` is safe;
the remedy is to select the intended interpreter/profile or deliberately
record and review a new baseline. No mismatch becomes an automatic refresh.

For target-set mismatches, retain sorted `missing` (requested without baseline
entry) and `stale` (baseline entry not requested) tuples. Improve the reason
to label those lists plainly and suggest checking explicit module selections
or recording a reviewed new baseline. Names are validated dotted Python
identifiers; do not print baseline paths or target stderr. Duplicate requested
names remain an error. Preserve existing error kinds, text/JSON exit behavior,
and the exact schema-1 JSON error shape (`schema_version`, `status`, `error`;
`error.kind` and `error.message`). Only message text and the additive typed
attribute change. A target-set error still precedes an environment probe in
the orchestrated `check` path, and any non-comparable state stops before
target imports.

## Ownership boundaries

- The schema-1 core owns invariant checks, pure refreshed values, identity
  differences, target-set details, and typed errors.
- The refresh CLI owns explicit file I/O, runtime selection, complete sampling,
  pre-commit change detection, replacement, and the text review summary.
- `check` and pytest only present shared errors and never mutate baselines.
- Users review changed medians and control comparable environments. Matching
  identity still does not establish statistical or cross-host equivalence.

## Validation and failure semantics

Issue #41 tests preserved per-target allowances, exact targets and sampling,
canonical bytes, sorted summary, non-comparable states before target imports,
missing/invalid/symlink files, external edits, atomic replacement, and old
bytes surviving failures and interruption before commit. It tests the commit
boundary without wall-clock assertions. The Windows, macOS, and Linux lanes
exercise the same file behavior. Issue #42 tests one and multiple identity
differences, fixed field order, `differing_fields`, sorted missing/stale sets,
safe redaction, existing JSON shape and exit codes, and no target imports on
non-comparable checks. Strict typing, 100% package branch coverage, build,
metadata, and clean-wheel checks remain in force.

## Compatibility and migration

Existing schema-1 baselines and schema-1 check reports remain valid with no
migration. The published threshold math, identity definition, target-set
semantics, `check`/pytest options, and exit codes do not change. Refresh is an
additive alpha API/CLI workflow, and `differing_fields` is an additive error
attribute. The changed prose of error messages is diagnostic text, not a new
machine field; callers should use `kind`, `differing_fields`, `missing`, and
`stale` rather than parse that text. Release notes must mention the new
workflow and the improved messages. A later schema or identity-policy change
requires a separate design and migration plan.

## Alternatives considered

Continuing to recommend `record --replace` is simple but can silently reset
per-target allowances. Editing timing values by hand avoids that reset but
does not verify the selected interpreter or complete sampling. Reusing
`check` to learn a new normal would let CI hide regressions and is rejected.
Allowing refresh to accept a new identity or target set behind another flag
would combine timing maintenance with policy migration; the first refresh
workflow deliberately keeps those decisions separate. Printing full baseline
and observed identities in errors would ease debugging but could reflect
user-supplied values. A field-only message with safe Python versions gives
useful guidance without that disclosure risk.

## Consequences and follow-up

- Issue #41 implements refresh without changing schema 1.
- Issue #42 implements shared, actionable mismatch diagnostics.
- A refresh still needs a human review; neither a successful command nor a
  matching identity proves that new timings are acceptable.
- Concurrent writers and crash durability remain outside this contract.

## Primary references

- [Python `os.replace` behavior](https://docs.python.org/3.11/library/os.html#os.replace)
- [Python temporary-file and directory behavior](https://docs.python.org/3.11/library/tempfile.html)
- [Python path and symlink inspection](https://docs.python.org/3.11/library/pathlib.html)
