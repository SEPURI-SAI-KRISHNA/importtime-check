# 0005: Parser and domain model contract

- Status: Accepted when the pull request containing this record merges
- Decision date: 2026-10-03
- Decision issue: [#19](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/19)
- Implementation issue: [#16](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/16)
- Initial implementation: [draft PR #17](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/pull/17)
- Owners: `importtime-check` maintainers

## Context

The package needs a stable boundary between CPython's textual import-time
diagnostics and later measurement, comparison, reporting, and integration
features. That boundary is public API: its names, values, ordering, failure
behavior, and supported input will constrain later work and users.

CPython's standard `-X importtime` output contains a header followed by rows
with self time, cumulative time, indentation, and a module name. Other messages
can share the stderr stream. Python 3.14 also added `-X importtime=2`, whose
already-loaded module rows contain `cached` instead of numeric timings. The
initial API needs an explicit policy for each kind of input without combining
parsing with process execution.

## Decision

### Public API

The package exports these names from `importtime_check`:

- `ImportTimeEvent`;
- `ImportTimeParseResult`;
- `ImportTimeParseError`; and
- `parse_importtime`.

`ImportTimeEvent` is a frozen, slotted dataclass with four fields:

- `module: str` is non-empty;
- `self_us: int` is a non-boolean, non-negative integer;
- `cumulative_us: int` is a non-boolean, non-negative integer no smaller than
  `self_us`; and
- `depth: int` is a non-boolean, non-negative, zero-based nesting depth.

`ImportTimeParseResult` is a frozen, slotted dataclass. Its `events` field is a
tuple of `ImportTimeEvent` values and its `diagnostics` field is a tuple of
strings. Construction copies both collections to tuples and validates their
members, so callers cannot mutate the result through a supplied list.

`ImportTimeParseError` is a `ValueError` with public `line_number`, `line`, and
`reason` attributes. The line number is one-based and the line is preserved
without its line ending.

### Parsing

`parse_importtime(stderr: str) -> ImportTimeParseResult` is a pure parser. It
performs no file, subprocess, environment, or network I/O.

The parser:

- ignores the exact standard header
  `import time: self [us] | cumulative | imported package`;
- accepts rows beginning with `import time:` followed by three pipe-separated
  columns containing numeric self time, numeric cumulative time, and a module;
- interprets timing values as integer microseconds without floating-point
  conversion;
- derives depth from two spaces per level before the module name;
- retains event order from the source stream; and
- retains non-prefixed logical lines, including internal blank lines, as
  diagnostics in source order.

A line beginning with `import time:` claims the parser's format. If it is not a
valid header or numeric event, parsing stops and raises `ImportTimeParseError`.
It is never silently reclassified as an unrelated diagnostic. A row containing
`cached` in a timing column is rejected with a focused explanation because
cached rows do not provide the numeric values required by this model.

The parser supports the numeric format emitted by the package's declared
CPython versions. Support for cached rows from Python 3.14's separate
`-X importtime=2` mode is outside this contract.

## Ownership boundaries

- This parser owns text recognition, immutable parsed values, and precise parse
  failures.
- A later execution layer will own invoking Python and capturing stderr.
- Later measurement logic will own target selection, sampling, aggregation,
  and regression decisions.
- Reporting and integrations will own presentation and transport of results.

## Validation and failure semantics

Tests cover headers, multiple events, source ordering, nesting, unrelated and
blank diagnostics, CRLF input, and input without a final newline. They also
cover malformed columns, non-numeric values, cached rows, invalid indentation,
missing module names, model invariants, immutable nested collections, exception
attributes, empty input, and exact public exports.

Malformed claimed rows fail at the first offending line. Empty input succeeds
with empty event and diagnostic tuples. Runtime dependencies remain empty. The
full formatting, linting, strict typing, coverage, build, metadata, artifact,
and clean-wheel checks apply to the implementation.

## Compatibility and migration

This is the first parser API and is introduced before the first public alpha,
so no user migration is required. After publication, the exported names, field
meanings, tuple ordering, immutability, and documented failure behavior are
compatibility commitments. New input formats should be added explicitly and,
where practical, additively.

Before publication, rollback is removal of the unpublished API. After
publication, incompatible changes require a new design record and the
project's versioning and migration process.

## Alternatives considered

Returning dictionaries or unnamed tuples was rejected because those forms make
the public contract less discoverable and easier to misuse. Treating malformed
prefixed rows as diagnostics was rejected because it can make incomplete
measurements appear successful. Modeling `cached` as an optional or sentinel
timing was deferred until cached-import behavior has an end-to-end use case.
Combining parsing with subprocess execution was rejected because a pure parser
is deterministic, independently testable, and reusable.

## Consequences and follow-up

- Later features receive one typed, ordered, immutable representation.
- Strict parsing exposes upstream format changes rather than hiding them.
- Users who intentionally request `-X importtime=2` cannot parse cached rows in
  this first API.
- Issue #16 may proceed under this contract after this record is merged.
- Draft PR #17 must use the current pull request template and pass the complete
  quality and artifact gates before it is marked ready for review.

## Primary references

- [Python `-X importtime` documentation](https://docs.python.org/3/using/cmdline.html#cmdoption-X)
- [CPython import-time output implementation](https://github.com/python/cpython/blob/main/Python/import.c)
