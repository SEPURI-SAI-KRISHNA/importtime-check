# 0009: Per-target baseline budgets

- Status: Accepted when the pull request containing this record merges
- Decision date: 2026-10-13
- Decision issue: [#57](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/57)
- Implementation issues: [#58](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/58)
  and [#59](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/59)
- Documentation follow-up: [#60](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/60)
- Extends: [0007](0007-regression-and-integration-contract.md) and
  [0008](0008-safe-baseline-refresh-and-diagnostics.md); replaces only
  ADR 0007's common-only baseline-creation inputs
- Owners: `importtime-check` maintainers

## Context

Schema-1 baselines already store absolute and percentage allowances on each
target. The shared comparison engine applies those stored values separately,
and `refresh` preserves them. However, the published `record_baseline` builder
and `baseline record` command can only set one allowance pair for every
target. A user must edit JSON by hand to record two modules with different
reviewed budgets. That bypasses the builder's validation and makes a
multi-module CI policy unnecessarily hard to reproduce.

## Decision

### A budget is a pair associated with one exact target

Add a public, immutable `TargetAllowance` value with named
`max_increase_us: int` and `max_increase_percent: str` fields. It follows
`TargetBaseline`'s existing non-boolean, non-negative integer validation and
ordinary non-negative decimal-string validation and normalization. Both
values are required; zero is valid. The target's measured upper median is
**not** part of this value. The new type is exported from `importtime_check`
and adds no runtime dependency.

Extend `record_baseline` with a keyword-only
`per_target_allowances: Mapping[str, TargetAllowance]` alternative. For
example:

```python
record_baseline(
    observations,
    environment,
    per_target_allowances={
        "email": TargetAllowance(max_increase_us=150, max_increase_percent="20"),
        "json": TargetAllowance(max_increase_us=25, max_increase_percent="10"),
    },
)
```

The existing keyword-only `max_increase_us` and `max_increase_percent` pair
remains supported with the same behavior and validation. A call must supply
**either** both common allowances **or** `per_target_allowances`, never a
partial pair, both modes, or neither mode. The implementation may use typed
overloads to preserve useful static checking of those two call forms. `None`
means an omitted mode argument; numeric zero is a real allowance, not an
omission. The per-target mapping must be non-empty and have exactly the
observation module keys. Unknown or missing keys fail with a deterministic
sorted explanation. Each value must be a `TargetAllowance`; a loose tuple,
dictionary, or `TargetBaseline` is not silently accepted. Mapping keys have
the existing dotted-module validation. A mapping cannot retain duplicate
keys; callers constructing one are responsible for detecting duplicates in
their own input format before conversion.

The builder validates the complete mode, environment, observations, and
allowance mapping before returning a new `Baseline`. It never changes input
objects, writes a file, probes an interpreter, or accepts partial results.
Targets remain sorted and immutable in the resulting baseline. The recorded
median for each target comes only from its complete observed sample set;
the new input supplies only that target's two allowances.

### The CLI accepts one repeated budget per recorded module

Add repeatable `--budget 'MODULE=US,PERCENT'` to `baseline record`. A
multi-target example is:

```console
importtime-check baseline record --output baseline.json --module email --module json --budget 'email=150,20' --budget 'json=25,10'
```

`--module` remains the explicit target list. In budget mode, every selected
module must have exactly one `--budget` entry and no budget may name a
different module. Duplicate module selections or duplicate budget entries
fail, even when their numeric values match. Module names use the existing
validator. Each entry has exactly one `=` and one `,` and no surrounding
whitespace. `US` is plain base-10 digits matching `(?:0|[1-9][0-9]*)`;
`PERCENT` uses the existing decimal-string grammar and normalization. No
sign, exponent, float, unit suffix, empty component, or extra delimiter is
accepted. Validation errors identify the bad module or entry without
printing child stderr or private runtime paths.

The existing common `--max-increase-us N --max-increase-percent P` path
remains valid, including its existing numeric parsing. Both common options
must be present together. They cannot be mixed with `--budget`, and there is
no default, inheritance, or precedence between modes. These conditions and
the entire target/budget association are validated **before** environment
probing, target imports, or file writing. Malformed CLI input remains a
usage error with exit code `2`; it never produces a partial baseline.

The new mode uses the same sampling, interpreter, profile, output path,
canonical schema-1 serialization, and atomic file-writing behavior as
today's `record`. After a successful budget-mode write, text output lists
the recorded modules in sorted order with their normalized allowances and
reminds the user to review the file diff. The old common-mode output may
remain unchanged. This summary is a review aid, not an approval or a claim
that a chosen budget is statistically justified.

### Replacement remains explicit and reviewable

An existing output file still requires `--replace`; neither mode modifies it
implicitly. Invalid options, duplicate or missing budgets, failed probing,
failed measurements, or failed encoding must leave an existing file unchanged.
The established atomic-write contract applies to the final commit. A valid
`--replace` request may deliberately alter target names, sampling, identity,
medians, and allowances, as `record` already can; it is **not** a safe
timing-only refresh. Reviewers must inspect the resulting baseline diff,
especially every allowance change, before accepting it as CI policy. Use
`baseline refresh --replace` from ADR 0008 when only medians should change:
refresh still preserves every per-target allowance and accepts no budget
options. Neither `check` nor pytest writes or learns budgets.

### Schema and verdicts do not change

No baseline or report schema version changes. The new inputs produce the
same exact schema-1 target fields as a hand-edited baseline, including
normalized percentage strings. Existing schema-1 files load unchanged.
`check`, JSON/text reporting, and the optional pytest adapter continue to
consume each target's stored allowances using ADR 0007's rule: an increase
is a regression only when it exceeds **both** that target's absolute and
percentage allowances. Target identity, upper-median sampling, equality
boundaries, output ordering, and exit codes remain unchanged.

## Ownership boundaries

- The core owns `TargetAllowance`, mode and exact-target validation, and
  construction of a complete schema-1 `Baseline` from observations.
- The CLI owns parsing repeated options, detecting duplicate entries before
  mapping conversion, validating all inputs before subprocess work, and
  presenting a review summary. It delegates value validation and baseline
  construction to the core where possible.
- Baseline serialization, comparison, refresh, and pytest keep their
  existing owners and do not infer new allowances.
- Users select and review budgets based on comparable measurements; the tool
  does not recommend or approve a threshold.

## Validation and failure semantics

Issue #58 tests both public call forms, zero and fractional allowances,
percentage normalization, exact target sets, invalid value types, the
non-empty mapping, deterministic ordering, immutability, schema-1 round
trips, and unchanged per-target comparison boundaries. Issue #59 tests the
CLI's complete two-module path, old common flags, missing/extra/duplicate
budgets, mixed and partial modes, malformed numeric syntax, validation before
probes/imports, exit code `2`, unchanged existing bytes on failure, and
explicit `--replace`. Include representative Windows, macOS, and Linux CI
coverage without wall-clock timing assertions. Existing Ruff, strict mypy,
100% package branch coverage, build, metadata, and clean-wheel gates remain.

## Compatibility and migration

This adds a public value type, a builder input mode, and a CLI option; it
does not invalidate old calls, commands, files, or reports. No baseline
migration is needed. The documented old common mode must keep its behavior;
new errors apply only to newly supplied or incomplete budget-mode inputs.
Release notes and the multi-module guide must show a deliberate policy
review and make clear that recorded allowances do not prove cross-host
comparability. If an implementation cannot preserve a published behavior,
stop and revise this design before merging it rather than silently changing
that behavior.

## Alternatives considered

Hand-editing schema-1 JSON can express per-target values today but bypasses
validated recording and is error-prone. Repeating `--budget` associates
values with exact module names; attaching numbers to positional `--module`
arguments would depend on order and make mistakes harder to spot. A separate
TOML/JSON policy file would create another format and source of truth for a
small input. Allowing common defaults plus per-target overrides would make
precedence and accidental policy inheritance more complex; the first
version requires one complete mode. Accepting bare tuples in the Python API
would be shorter but makes the two numeric roles positional and easier to
reverse. An automatic calibration or learning mode would turn ordinary
measurement noise into CI policy and is excluded.

## Consequences and follow-up

- Issue #58 implements the public value and builder without changing schema 1.
- Issue #59 implements the CLI input and review summary.
- Issue #60 updates the README and a runnable multi-module CI example.
- Users still need a controlled environment and reviewed allowances. A
  matching five-field identity does not guarantee comparable host load or
  dependencies; this feature does not solve timing noise.

## Primary contracts

- [ADR 0007: baseline schema and exact threshold arithmetic](0007-regression-and-integration-contract.md)
- [ADR 0008: timing-only refresh and preserved allowances](0008-safe-baseline-refresh-and-diagnostics.md)
