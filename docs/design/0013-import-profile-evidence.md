# 0013: Import-profile evidence and hotspot interpretation

- Status: Accepted when the pull request containing this record merges
- Decision date: 2026-11-10
- Decision issue: [#112](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/112)
- Milestone: [0.3.0a1](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/milestone/7)
- Extends: [0005](0005-parser-and-domain-model-contract.md),
  [0006](0006-isolated-measurement-and-sampling.md), and
  [0010](0010-multi-target-measurement-reports.md)
- Implementation issues: [#113](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/113),
  [#114](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/114),
  [#115](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/115),
  and [#116](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/116)
- Owners: `importtime-check` maintainers

## Context and meaning

`ImportMeasurement.parsed.events` already contains ordered numeric CPython
`-X importtime` rows for one isolated import. The version-1 measurement report
deliberately retains only target totals. It cannot preserve repeated module
names, self time, cumulative time, or the row order needed to investigate an
import hotspot. A profile is **opt-in observation evidence**, not a baseline,
regression verdict, flame graph, or proof of why an import was slow.

CPython defines self time as excluding nested imports and cumulative time as
including them. Cumulative values from nested rows overlap: adding them does
not yield elapsed process time. `-X importtime` may produce broken output in a
multithreaded application. This contract accepts only the existing numeric
mode; Python 3.14's `-X importtime=2` cached rows remain unsupported by ADR
0005. The existing parser and target-event selection stay authoritative.

## Decision

### Capture is an explicit, bounded Python operation

Export `capture_import_profile(modules: Sequence[str], *,
python_executable=None, timeout_seconds=30.0, working_directory=None,
warmups=1, samples=5) -> ImportProfile`. It uses ADR 0006/0010's validated
module names, isolated interpreter, environment snapshot, per-child timeout,
fresh sequential children, warmup/sample order, and failure indexing. It must
not import a target into the caller, retry a failed run, or launch a second
target import merely to obtain events. A separate safe interpreter-identity
probe may run before sampling; it does not import any selected target. Profile
capture does not alter `measure_import`, `sample_import`, or `sample_imports`.

Validate the entire request before starting any child: 1–16 distinct targets,
0–5 warmups, 1–20 recorded samples, and at most 100 target runs in total
(`len(modules) * (warmups + samples) <= 100`). Sort targets by exact name;
within each target, retain warmups then samples in execution order. A failed
probe, target, or later run returns no `ImportProfile` and no partial artifact.
Existing `ImportMeasurementError` keeps its module, phase, and one-based run
number. Capture-specific limit failures use `ImportProfileError(kind="limit")`
with the selected module and run, without echoing raw stderr.

The profile path must bound each child's captured stderr to 2 MiB before
parsing, including unrelated diagnostics. On overflow, terminate and reap the
direct child and fail; never truncate a stream into apparently complete
evidence. This is an opt-in bound, not a change to the published measurement
APIs. It does not claim to stop descendants spawned by a target. After a
complete parse, accept at most 5,000 events per run and 50,000 events across
the profile. Count and byte limits fail closed, never silently drop rows.

Public profile values are frozen, slotted, and validated. `ImportProfile`
contains the four safe interpreter identity fields (`implementation`, Python
major.minor, `platform`, `machine`), sampling counts/statistic, ordered
target/run values, and optional `source_sha256` provenance metadata. The
digest metadata is not a serialized field. Each run identifies its `phase`
(`warmup` or `sample`), one-based `number`, and ordered tuple of existing
`ImportTimeEvent` values.
For each run, exactly one event must match its target; this is the same target
selection invariant as `ImportMeasurement`. Repeated *other* module names are
separate occurrences, not an error or an aggregation key. No stderr
diagnostics, executable path, working directory, process environment, or
timestamps enter the public profile.

For example, `capture_import_profile(("json", "email"), warmups=1,
samples=2)` returns sorted targets `email`, `json`, each with run identifiers
`(warmup, 1)`, `(sample, 1)`, `(sample, 2)`. The sample upper median remains
ADR 0006's target-total statistic; the profile does not select a
"representative" event trace from those runs.
`capture_import_profile(("json", "json"))` instead raises `ValueError` before
any interpreter or target child starts.

### Separate version-1 artifact, exact source-byte digest

Export `encode_import_profile(profile: ImportProfile) -> bytes` and
`load_import_profile(path: str | os.PathLike[str]) -> ImportProfile`.
Encoding performs no I/O and emits UTF-8 JSON with sorted object keys,
two-space indentation, and one trailing newline. The loader reads one
existing regular, non-symlink file, without importing modules or running a
child. It accepts semantically valid noncanonical JSON but records
`source_sha256` from the **exact bytes read**. A captured profile has
`source_sha256=None`; callers may separately hash encoded bytes. Re-encoding a
loaded profile does not change what its original `source_sha256` identifies.

The artifact has exactly these top-level keys: `environment`,
`profile_type`, `profile_version`, `sampling`, and `targets`.
`profile_type` is `"import-profile"` and `profile_version` is the non-boolean
integer `1`. `environment` has exactly `implementation`, `machine`,
`platform`, and `python`, with ADR 0010's safe meanings. `sampling` has
exactly `warmups`, `samples`, and `statistic: "upper_median"`. `targets` is a
non-empty mapping from valid dotted target names to objects containing only
`runs`. Each run has exactly `phase`, `number`, and `events`; each event has
exactly `module`, `self_us`, `cumulative_us`, and `depth`. Event times are
non-boolean integers from 0 to 2^63−1 microseconds, with `cumulative_us >=
self_us`; depth is a non-boolean integer from 0 to 5,000. Event module names
must be valid dotted identifiers no longer than 256 UTF-8 bytes, rather than
arbitrary stderr text. A captured event outside these bounds fails the whole
opt-in profile, even if the ordinary parser can represent it.
The loader validates the target's unique event, count limits, complete run
sequence, and all exact keys, regardless of JSON object-key order.

An illustrative complete one-target, one-sample artifact follows. The two
`json.decoder` rows are intentionally distinct occurrences; the numbers are
invented and are not recommended thresholds:

```json
{
  "environment": {
    "implementation": "cpython",
    "machine": "x86_64",
    "platform": "linux",
    "python": "3.11"
  },
  "profile_type": "import-profile",
  "profile_version": 1,
  "sampling": {
    "samples": 1,
    "statistic": "upper_median",
    "warmups": 0
  },
  "targets": {
    "json": {
      "runs": [
        {
          "events": [
            {"cumulative_us": 8, "depth": 1, "module": "json.decoder", "self_us": 6},
            {"cumulative_us": 9, "depth": 1, "module": "json.decoder", "self_us": 6},
            {"cumulative_us": 25, "depth": 0, "module": "json", "self_us": 2}
          ],
          "number": 1,
          "phase": "sample"
        }
      ]
    }
  }
}
```

Reject a version-1 measurement report or schema-1 baseline as the wrong
`profile_type`, a future `profile_version`, duplicate JSON keys, non-finite
numbers, invalid UTF-8, unknown fields, missing runs, duplicate or out-of-order
run numbers, an absent/duplicate target event, cached/non-numeric times, and
event counts beyond the limits. Read at most 8 MiB plus one byte to detect an
oversized file; apply the same 8 MiB UTF-8 limit to encoded output. Never
accept a prefix of a truncated or oversized document. An invalid file raises
`ImportProfileError` with a safe category (`io`, `oversized`,
`unsupported-version`, or `invalid`), not a partial profile or raw file text.
For example, changing the JSON above to `"profile_version": 2` raises
`unsupported-version`; supplying a measurement report v1 as a profile raises
`invalid`. Neither is treated as an empty or partial profile.

### Inspect one selected run, never a synthetic trace

Export `inspect_import_profile(profile: ImportProfile, *, target: str,
phase: Literal["warmup", "sample"], run_number: int, limit=20) ->
ProfileInspection`. Both API and `profile show --file PATH --target MODULE
--phase warmup|sample --run N [--limit N] [--format text|json]` require the
caller to select an existing target, phase, and one-based run number. No
default "best", median, or latest run is chosen. `limit` is a non-boolean
integer from 1 to 100. `ProfileInspection` identifies the selected evidence
and provides separate self-time and cumulative-time rankings; each row carries
its one-based original occurrence index, module, depth, and both timings.

Sort each ranking by descending selected time and then ascending original
occurrence index. Do not collapse repeated names, infer a parent graph from
indentation, sum cumulative values, or mix events from different runs. For the
example above, self-time order is occurrences 1, 2, 3 (the tie preserves
source order); cumulative-time order is 3, 2, 1. A claim that cumulative
time totals `8 + 9 + 25 = 42 µs` would double count overlapping imports and
is prohibited. The selected target's `25 µs` is an observation, not proof
that either decoder row caused a regression.

The text and JSON CLI formats name the artifact's exact source digest, safe
environment identity, target, phase, run, sort metric, and original occurrence
indices. Output is bounded by `limit`, deterministic for fixed evidence, and
labels cumulative timing as overlapping. A captured in-memory profile may be
inspected through the API without a source digest; neither CLI nor API invents
one. `profile show` is read-only. It has no upload, baseline, check, or pytest
side effect. Expected bad file/selection/limit failures exit `2` with concise
stderr and **empty stdout**; success exits `0`, never regression exit `1`.
Argument syntax errors retain the CLI's usual usage behavior.
For the example artifact, requesting `--target json --phase sample --run 2`
fails with exit `2` and empty stdout: there is no second sample to inspect.

## Ownership, privacy, and validation

- ADR 0005's parser owns numeric row recognition; the capture layer owns
  bounded child output and complete target/run evidence. Artifact code owns
  schema, canonical encoding, exact-byte digest, and strict offline loading.
  Inspection owns ranking and presentation. Baseline/check/pytest never read
  profile files or use hotspot rankings as policy.
- This format deliberately omits raw stderr, unrelated diagnostics, paths,
  dependency versions, runner labels, and secrets. Module identifiers can
  still reveal project structure; users must review artifacts before sharing.
  An exact digest proves bytes, not origin, host comparability, or truth of
  an asserted environment identity. No automatic upload is introduced.
- Issue #113 tests pre-launch validation, one snapshot and safe probe,
  deterministic target/run/event order, repeated names, bounded stderr,
  cleanup, later-run failure, and real isolated children. Issue #114 tests
  canonical round trips, exact source-byte digests, every strict rejection
  above, byte/count boundaries, and archived version-1 compatibility.
  Issue #115 tests both rankings, ties, zeros, repeated names, explicit
  selection, output limits, safe diagnostics, and installed-wheel CLI output.
  Issue #116 adds archived profile fixtures and cross-platform installed-wheel
  capture/load/show checks; assert structure, not exact timing values.
- Existing Ruff, strict mypy, full tests with 100% package branch coverage,
  build, Twine, artifact, clean-wheel, CodeQL, and supported-Python CI gates
  remain required for the implementation PRs. The design PR changes no code
  or serialized production output.

## Compatibility, alternatives, and rollback

This is additive to the published alpha. Existing parser behavior,
`ImportMeasurement`, measurement report v1, offline report cohorts, schema-1
baselines, `measure`, `report`, `check`, and optional pytest gate remain
unchanged. A profile file cannot be mistaken for an existing report or
baseline. Future incompatible profile shapes require a new
`profile_version`, archived compatibility fixtures, and migration guidance;
version 1 must not be silently reinterpreted. Before implementation, the ADR
can be revised in review. After publication, rollback disables the new
opt-in profile path without rewriting historical evidence or changing policy.

Embedding events into measurement report v1 would break its strict readers.
Archiving raw stderr would retain unrelated diagnostics and potentially
private data. Re-running a median sample to capture a "representative" trace
would produce different evidence; picking one existing sample without naming
it would be misleading. Aggregating cumulative times or repeated names would
discard occurrence context and invite false causal claims. A permissive
loader could turn truncated evidence into an apparently valid profile.

## Primary references

- [Python `-X importtime` semantics and multithreaded warning](https://docs.python.org/3/using/cmdline.html#cmdoption-X)
- [ADR 0005: numeric parser and cached-row exclusion](0005-parser-and-domain-model-contract.md)
- [ADR 0006: isolated sampling and failure semantics](0006-isolated-measurement-and-sampling.md)
- [ADR 0010: version-1 measurement report boundary](0010-multi-target-measurement-reports.md)
