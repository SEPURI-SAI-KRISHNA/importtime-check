# 0007: Baselines, regression decisions, and integration contract

- Status: Accepted when the pull request containing this record merges
- Decision date: 2026-10-04
- Decision issue: [#24](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/24)
- Implementation issues: [#25](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/25),
  [#26](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/26), and
  [#27](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/27)
- Owners: `importtime-check` maintainers

## Context

ADR [0006](0006-isolated-measurement-and-sampling.md) yields ordered import
measurements and an observed upper median. It does not say which runs may be
compared, how a baseline is reviewed in version control, what increase is
allowed, or how a failure reaches CI. Those choices must be shared by the
library, command-line interface, and optional pytest adapter. This record
defines the first pre-alpha contract; it does not implement it.

## Decision

### Baseline schema and identity

The baseline is a UTF-8 JSON object with `schema_version` equal to the JSON
integer `1`. Its exact top-level keys are `schema_version`, `environment`,
`sampling`, and `targets`. A representative file is:

```json
{
  "environment": {
    "implementation": "cpython",
    "machine": "amd64",
    "platform": "win32",
    "profile": "default",
    "python": "3.11"
  },
  "sampling": {
    "samples": 5,
    "statistic": "upper_median",
    "warmups": 1
  },
  "schema_version": 1,
  "targets": {
    "json": {
      "baseline_cumulative_us": 420,
      "max_increase_percent": "10",
      "max_increase_us": 25
    }
  }
}
```

`environment` has exactly the five shown keys. `implementation` is the
selected interpreter's `sys.implementation.name`, and must be `cpython` in
schema 1. `python` is its major.minor version, not its patch version.
`platform` is its `sys.platform`; `machine` is its non-empty
`platform.machine()` after stripping whitespace and lowercasing. These four
values come from a bounded, isolated probe of the **selected interpreter**, not
the process running the checker. `profile` is a non-blank user-supplied label,
defaulting to `default`, for intentionally separate dependency or deployment
contexts. All five fields must match exactly before any target import runs.

The executable path, hostname, virtual-environment path, Python patch version,
timestamps, and dependency inventory are not identity fields. Paths and hosts
are too ephemeral for a reviewed baseline; pinning the patch version would
needlessly invalidate it after routine patch updates. Dependency versions,
patch releases, CPU load, and environment variables can still affect import
time. Users must maintain comparable environments and use distinct profiles or
refresh baselines when those factors materially change. A matching identity is
permission to compare, not proof that the machines are equivalent.

`sampling` has exactly `warmups`, `samples`, and `statistic`. The counts follow
ADR 0006's non-boolean integer rules, and `statistic` is exactly
`upper_median`. A comparison must use these stored counts and statistic; CLI
or pytest options cannot silently override them.

`targets` is a non-empty object keyed by valid dotted module names as defined
in ADR 0006. Each target has exactly the three shown keys. The baseline and
absolute allowance are non-boolean, non-negative integer microseconds. The
relative allowance is a finite, non-negative **decimal string** in ordinary
notation matching `(?:0|[1-9][0-9]*)(?:\.[0-9]+)?`, with no sign or
exponent: `0`, `2`, `2.5`, and `0.25` are valid. JSON numeric values and
leading-zero forms such as `02` are not valid percentages. Both allowances are
required, and either may be zero. Different targets may
have different allowances. Baseline creation CLI flags set common initial
allowances; users may edit per-target values in the JSON file.

### Serialization and file failures

Writers produce exactly one JSON document with UTF-8, no BOM, two-space
indentation, lexicographically sorted object keys, `ensure_ascii=False`,
`allow_nan=False`, and a single final LF. They write LF on every platform.
Relative-percent strings are normalized by removing redundant leading and
trailing zeroes, while retaining `0` for zero. The format contains no measured
sample arrays, timestamps, or local paths, so identical baseline data produce
identical bytes. Writes use a temporary file in the destination directory and
an atomic replacement; an existing baseline is never overwritten without an
explicit `replace` request.

Readers accept harmless JSON whitespace and key order differences, then
validate the complete schema. They reject invalid UTF-8, duplicate object
keys, unknown or missing fields, non-finite JSON numbers, booleans in integer
fields, floating-point timing values, empty target sets, invalid module names,
and unsupported schema versions. Non-finite constants such as `NaN` are
rejected during decoding even where a permissive JSON decoder accepts them.
A malformed or unavailable file raises a typed baseline error with a concise
reason, never an empty baseline. Unknown
future versions fail explicitly; there is no best-effort interpretation.

### Threshold arithmetic and verdicts

For a target let `B` be its baseline median, `C` the current recorded median,
`A` its absolute allowance in microseconds, and `R` its relative allowance in
percent. Let `D = max(C - B, 0)`. The target is a regression **only if both**
`D > A` and `100 * D > B * R`. Equality at either boundary passes. A decrease
or unchanged value passes. When `B = 0`, relative allowance contributes zero;
the absolute allowance determines whether a positive result passes.

No binary float, interpolation, or rounding is used for this decision.
Implementations parse `R` as integer digits `n` and scale `10^k`, then compare
`100 * D * 10^k > B * n` using integers. For example, `B = 101`, `A = 5`,
`R = "5"` permits
`C = 106` but rejects `C = 107`; a fractional 5.05-microsecond allowance is
never rounded first. Setting both allowances to zero rejects any increase.
The overall verdict is `regression` if any target regresses, otherwise `pass`.

### Target sets, errors, and the shared engine

The requested target set must exactly equal the baseline's target keys.
Targets requested without a baseline entry are `missing`; baseline entries no
longer requested are `stale`. The engine reports both sets sorted and refuses
to compare. When no target list is supplied, all baseline targets are
requested; this cannot detect a target removed from an external project plan,
so CI should supply its intended target list explicitly. Duplicate requested
names are invalid. Environment mismatch, malformed files, unsupported schema,
target-set mismatch, and measurement or interpreter-probe failures are errors,
not regression verdicts. They must fail closed without using partial samples.

A standard-library-only core owns baseline parsing, identity checks,
measurement orchestration, exact threshold evaluation, and structured results.
The CLI and pytest integration call that same engine; neither reimplements
threshold math. Successful results include immutable per-target data in module
name order: baseline and current medians, signed `change_us`, allowances,
`pass`/`regression`, ordered warmup and recorded cumulative values, and a
diagnostic snapshot. The snapshot uses the **first** recorded run equal to the
median and lists its five highest-self-time import events, descending by
`self_us` with original parse order breaking ties. Each event retains module,
self and cumulative microseconds, and depth. This is a clue for investigation,
not an attribution of the entire regression to those imports.

### CLI and machine report

The distribution exposes `importtime-check` with two first-release workflows:

- `importtime-check baseline record --output FILE --module MODULE ...
  --max-increase-us N --max-increase-percent P` records a baseline. Optional
  `--warmups`, `--samples`, `--python`, `--timeout-seconds`,
  `--working-directory`, and `--profile` use ADR 0006 defaults where relevant.
  `--replace` is required to replace an existing file.
- `importtime-check check --baseline FILE` checks all stored modules, or uses
  repeated `--module` flags as an explicit exact target-set assertion. Optional
  `--python`, `--timeout-seconds`, `--working-directory`, and `--profile`
  select the current runtime. `--format text|json` defaults to `text`.

There is no implicit pyproject, environment-variable, or network
configuration. Explicit CLI options override only runtime defaults; the
baseline owns target thresholds and sampling counts. Paths are resolved from
the invocation directory. Standard output holds the text or JSON report;
human-facing errors go to standard error. `record` exits `0` on success and
`2` on input, measurement, or write error. `check` exits `0` for pass, `1` for
regression, and `2` for any non-comparable or operational error. User
interruption propagates rather than being reported as a completed check.

JSON check output is versioned independently with `schema_version: 1` and
`status: "pass" | "regression" | "error"`. For pass or regression it has
exactly `schema_version`, `status`, `environment`, and `results`. `results` is
an array sorted by module; each entry has `module`, `status`,
`baseline_cumulative_us`, `current_cumulative_us`, `change_us`,
`max_increase_us`, `max_increase_percent`, `warmups_cumulative_us`,
`samples_cumulative_us`, and `top_imports`. The two sample arrays preserve run
order. `top_imports` contains objects with `module`, `self_us`,
`cumulative_us`, and `depth`. For an operational error the output instead has
exactly `schema_version`, `status: "error"`, and `error`, whose `kind` and
`message` are required and whose `module`, `run_phase`, and `run_number` are
present when available. Error `kind` is one of `baseline-missing`,
`baseline-invalid`, `schema-unsupported`, `environment-mismatch`,
`target-set-mismatch`, `interpreter-probe-failed`, `measurement-failed`, or
`io-error`. JSON mode emits one such object on stdout even when
`check` exits `1` or `2`; CLI syntax errors from argument parsing exit `2`
with parser diagnostics rather than a JSON object. JSON uses the same
canonical encoding rules as baselines. The report never embeds full stderr,
absolute interpreter paths, or arbitrary target output; detailed exceptions
remain available to library callers.

### Optional pytest adapter

Pytest support is opt-in through `pytest -p importtime_check.pytest_plugin`;
there is no automatic `pytest11` entry point. The module may be shipped in
the wheel but is not imported by the core package or CLI. A `pytest` extra
may install pytest for users who want the adapter; pytest is never a core
runtime dependency. Loading the plugin without a baseline is a usage error.

The plugin accepts `--importtime-baseline` and optional repeated
`--importtime-module`, `--importtime-python`, `--importtime-timeout-seconds`,
`--importtime-working-directory`, and `--importtime-profile`. Corresponding
pytest configuration keys are `importtime_baseline`, `importtime_modules`,
`importtime_python`, `importtime_timeout_seconds`,
`importtime_working_directory`, and `importtime_profile`. Explicit plugin CLI
values replace their configuration-file counterpart; repeated CLI modules
replace, rather than extend, configured modules. Otherwise the baseline
supplies its target set and sampling policy, and ADR 0006 supplies runtime
defaults. No pytest test collection or test marker implicitly changes the
measured target set.

Configuration and baseline validation happen before tests; invalid settings,
missing or stale targets, and environment mismatch are pytest usage errors
(exit code `4`). After an otherwise successful test session, the plugin runs
the shared check once and prints a clearly labeled terminal summary. A
regression or measurement error changes an otherwise `0` exit to pytest's
test-failed code `1`, with distinct `regression` or `error` wording and run
context. If pytest already has a nonzero status, including interruption or no
tests collected, the plugin skips measurement and preserves that status.
These are session-level gate results, not fabricated individual test results.
The plugin must not write or refresh a baseline.

## Ownership boundaries

- ADR 0006 owns subprocess isolation, individual observations, sampling,
  timeout, and run-indexed measurement failures.
- The core baseline engine owns schema validation, environment and target-set
  comparison, exact threshold math, immutable report data, and deterministic
  serialization.
- CLI and pytest own option parsing, presentation, and process exit behavior,
  while consuming the same core verdict.
- Users own baseline review and comparable build environments. A successful
  gate is evidence under this policy, not a universal performance claim.

## Validation and failure semantics

Issue #25 tests canonical byte output, schema versions, malformed and duplicate
keys, invalid numeric types, exact threshold boundaries (including zero and
fractional percentages), environment and target mismatches, atomic-write
behavior, and shared result ordering. Issue #26 tests CLI exit codes, JSON
schemas, stderr/stdout separation, and packaged entry points. Issue #27 tests
plugin opt-in, precedence, optional imports, regression and operational
failure statuses, and preservation of existing pytest failures. No test uses
wall-clock timing as an expected value. Ruff, strict mypy, 100% package
branch coverage, build, metadata, artifact, and clean-wheel checks remain
required.

## Compatibility and migration

This design precedes the first release, so no migration is needed. Once
published, baseline and report schema versions, field meanings, threshold
boundaries, CLI exit codes, and documented pytest options are compatibility
promises. New optional fields or changed identity criteria need a new schema
version and an explicit migration; readers never guess an unknown version.
Incompatible API changes follow ADR 0001's versioning policy. Before the
first release, rollback is removal of unpublished formats and adapters.

## Alternatives considered

TOML is pleasant to edit but JSON has a standard-library reader and writer,
unambiguous numeric arrays, and straightforward machine consumers. A single
global threshold would be simpler but cannot express target-specific budgets.
Absolute-only and relative-only limits each behave poorly across very small
and larger baselines; requiring an increase to exceed **both** gives both
controls a role. Floating-point percentages or pre-rounded allowances risk
changing boundary verdicts. Implicitly comparing every host or pinning exact
interpreter paths would respectively be too weak or too brittle. Duplicating
comparison code in adapters risks contradictory CI outcomes. An auto-loaded
pytest plugin or required pytest dependency would surprise core users.

## Consequences and follow-up

- Issue #25 implements schema 1 and the shared baseline/verdict engine.
- Issue #26 adds the CLI and stable human/JSON reports.
- Issue #27 adds the opt-in pytest adapter and extra.
- Baselines are intentionally reviewable but must be updated when the
  environment or intended targets change; the tool does not silently learn a
  new normal.
- The first gate reduces one-run noise but does not claim statistical
  significance or compare unrelated machines reliably.

## Primary references

- [Python JSON encoder and decoder](https://docs.python.org/3/library/json.html)
- [Python decimal arithmetic](https://docs.python.org/3/library/decimal.html)
- [Pytest plugin loading](https://docs.pytest.org/en/stable/how-to/plugins.html)
- [Pytest hooks and configuration options](https://docs.pytest.org/en/stable/reference/reference.html)
- [Pytest exit codes](https://docs.pytest.org/en/stable/reference/exit-codes.html)
