# 0002: Quality and test policy

- Status: Accepted
- Acceptance: merge of the pull request that adds this record
- Decision date: 2026-10-02
- Decision issue: [#7](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/7)
- Owners: `importtime-check` maintainers

## Context

Quality tools affect contributor environments, continuous integration, and the
evidence behind compatibility claims. If their responsibilities overlap or
their configuration is allowed to weaken silently, a green check can stop
meaningfully describing the package that users receive.

Development tools must also remain separate from the published package.
`importtime-check` has a zero-dependency core contract, so adding linters, test
runners, or build tools to runtime dependencies would violate ADR 0001. Package
extras are published as optional user-facing metadata and are therefore also
the wrong place for repository-only tools.

This record defines policy before tracked tool configuration and tests are
added. Exact dependency versions and configuration syntax belong to later
implementation issues, but those implementations must preserve the boundaries
and command behavior established here.

## Decision

### Development dependencies

Unpublished development requirements will use the standardized
`[dependency-groups]` table in `pyproject.toml`. The initial groups are:

- `test` for pytest, coverage measurement, and test-only helpers;
- `quality` for Ruff and mypy;
- `packaging` for the PEP 517 build frontend, Twine, and artifact inspection
  helpers; and
- `dev`, composed from the other three groups with dependency-group includes.

Dependency groups are inputs to development environments. They are not written
to core metadata, are not installable package extras, and do not alter the
empty runtime dependency list. Optional extras remain reserved for features
that users intentionally install, such as the future pytest integration.

The implementation issue will choose reviewed lower bounds that support the
adopted configuration. Dependency refreshes must be explicit changes with all
quality and artifact checks rerun; they must not be incidental to unrelated
source changes.

### Formatting and linting

Ruff owns Python formatting and lint diagnostics. It will target Python 3.11,
the package syntax floor, and use an explicit stable rule selection. Preview
rules are disabled unless a dedicated issue documents the migration and the
repository is clean under the proposed behavior.

The required checks are:

```console
python -m ruff format --check .
python -m ruff check .
```

Commands use the repository root so maintained Python scripts are included.
Ruff does not own prose or Python examples embedded in Markdown; if those need
executable or style validation, a dedicated documentation checker must be
configured and named rather than implied by the Ruff checks.

Formatting changes are not accepted as substitutes for lint fixes. Autofix may
be used locally, but maintainers must review its resulting diff and CI runs the
non-mutating commands above.

### Static typing

Mypy owns static type checking for package source, tests, and maintained Python
scripts. It will run in strict mode with configuration-warning detection
enabled. The required command, once all three paths exist, is:

```console
python -m mypy src tests tools
```

A missing maintained path may be omitted only until the issue that creates it;
CI must not silently omit a path that exists. A repository-wide
`ignore_missing_imports` setting is prohibited because it can conceal broken
integration boundaries. An untyped third-party package must instead receive a
narrow module-specific override with an explanation and, when practical, a
tracking issue for removal.

Mypy verifies type consistency; it does not replace runtime tests, validate
serialized data, or prove that platform-specific branches execute correctly.

### Test runner and test isolation

Pytest owns test discovery, execution, marker registration, and assertion
reporting. Configuration must enable strict configuration parsing, strict
marker validation, and strict expected-failure behavior. The ordinary test
command is:

```console
python -m pytest
```

Unit tests must be deterministic and offline. They must not depend on network
access, wall-clock sleeps, production credentials, mutable global machine
state, execution order, or files outside test-controlled temporary locations.
Time, environment variables, subprocess inputs, and randomness must be
controlled explicitly. Subprocess tests require bounded timeouts; a sleep is
not synchronization.

Tests that genuinely require an external engine, service, or platform facility
must use a registered integration marker and a separately configured workflow.
They must use test credentials and isolated resources, document cleanup, and
never turn an unavailable production service into an apparent unit-test pass.

### Coverage

Coverage.py, invoked through pytest-cov, owns coverage collection and reporting
for `src/importtime_check`. Branch measurement is mandatory. The canonical
explicit gate is:

```console
python -m pytest --cov=importtime_check --cov-branch \
  --cov-report=term-missing --cov-fail-under=100
```

The initial threshold is 100% for both statements and branches in package
source. Tests, generated artifacts, `.tmp`, and development tooling are outside
the package-source denominator, but no package module may be omitted merely to
make the number pass.

Lowering the threshold or excluding package code requires an evidence-based
issue that identifies the exact unreachable or unsafe-to-exercise behavior,
considers a design change that makes it testable, and records the smallest
temporary exception. A later pull request must remove the exception when its
reason no longer applies.

### Builds and artifact validation

The `build` frontend owns isolated PEP 517 creation of one source distribution
and one wheel. Twine owns standards-oriented metadata and description checks.
Neither replaces content inspection or an installation test. The baseline
commands are:

```console
python -m build --outdir .tmp/dist
python -m twine check .tmp/dist/*
```

Validation must then inspect both archives for the expected names, versions,
license files, package files, typed-package marker, and absence of unintended
runtime requirements. It must fail if the wheel and source distribution
disagree.

The wheel from `.tmp/dist` must be installed with `--no-deps` and `--no-index`
into a newly created virtual environment located outside the source import
path. That environment must run an isolated-mode import and compare
`importtime_check.__version__` with installed distribution metadata. Editable
installs and imports from the checkout are not artifact evidence. Release
automation must publish the exact artifacts that passed these checks rather
than rebuild them.

The maintained validator will resolve exactly one wheel to an absolute path and
substitute the environment-specific interpreter for `<clean-python>` in these
required command shapes:

```console
python -m venv .tmp/wheel-smoke
<clean-python> -m pip install --no-index --no-deps <absolute-wheel-path>
<clean-python> -I -c "import importlib.metadata as m; import importtime_check as p; assert p.__version__ == m.version('importtime-check')"
```

The last command must run with a working directory that does not contain the
source tree on its import path.

## Ownership boundaries

- `[dependency-groups]` owns unpublished development-environment inputs;
  `[project].dependencies` and `[project.optional-dependencies]` own published
  user installation metadata.
- Ruff owns Python formatting and lint rules, not typing, runtime behavior, or
  Markdown validation.
- Mypy owns static type consistency across maintained Python code, not runtime
  assertions.
- Pytest owns discovery and test execution; pytest-cov and Coverage.py own the
  measured package-source coverage gate.
- The build frontend and Hatchling own artifact construction; Twine owns its
  metadata checks; repository validation owns archive contents and clean-wheel
  behavior.
- Test modules own deterministic setup and cleanup. Integration workflows own
  external resources they provision.
- CI owns repeatable execution of these commands across the supported Python
  and operating-system matrix. Local success is useful but does not replace
  required CI evidence.

## Exceptions and suppressions

An exception must be narrower and more visible than the rule it relaxes:

- Ruff `noqa` comments and mypy error-code suppressions must name the precise
  diagnostic and include a nearby reason when the code is not self-explanatory.
- File-wide ignores, per-module overrides, and coverage exclusions require a
  documented technical limitation; directory-wide blanket ignores are not
  permitted for maintained code.
- A skipped test must state a concrete runtime reason. A persistent missing
  capability or defect requires a tracking issue; an ordinary regression must
  fail rather than skip.
- Expected failures must be strict, narrowly matched, and linked to a tracked
  defect. An unexpected pass is a failure so obsolete workarounds are removed.
- Platform conditions may select real platform behavior, but must not disguise
  an unsupported platform as passing.

Tool-version updates must remove obsolete exceptions. New suppressions receive
the same review as source behavior and must not be generated wholesale.

## Validation and failure semantics

A quality validation is successful only when every configured check exits zero
and produces evidence for the intended scope. In particular:

1. Ruff formatting and lint checks run from the repository root.
2. Strict mypy covers source, tests, and maintained Python scripts.
3. Pytest rejects unknown configuration and markers, and all required tests
   pass without order or machine-state dependencies.
4. Package source reaches 100% statement and branch coverage.
5. An isolated PEP 517 build produces exactly one expected wheel and source
   distribution, and Twine accepts both.
6. Archive inspection and a clean, offline, dependency-free wheel installation
   satisfy ADR 0001's metadata, content, import, and version contracts.

Warnings that indicate invalid tool configuration, uncollected intended tests,
or an unknown marker are failures. A skipped required test is not equivalent
to a pass. A tool unavailable in a contributor environment may be reported as
such locally, but required CI lanes must provision it and cannot waive the
check.

## Compatibility and change policy

Configuration may become stricter in an ordinary reviewed change when the
repository already passes it. Weakening strict mode, reducing coverage,
removing a maintained path, broadening an ignore, or dropping an artifact
check requires an issue with evidence and migration consequences. Material
changes to the tool ownership or dependency boundary normally require a
superseding design record.

No dependency lock file is required initially. The supported multi-version,
multi-platform matrix, reviewed lower bounds, isolated builds, recorded CI
environments, and publication of already-validated artifacts provide the first
reproducibility controls. Resolver drift, security response, or a larger tool
set may justify a reviewed lock strategy later.

## Alternatives considered

### Development extras

A `dev` or `test` package extra is familiar, but extras are published as
user-facing package metadata. Repository-only tools belong in unpublished
dependency groups so installing an optional product feature remains distinct
from preparing a checkout.

### Requirements files

Separate requirements files work with older installers, but introduce another
dependency declaration surface and require manual composition. Standardized
dependency groups keep the repository requirements and group relationships in
`pyproject.toml` without publishing them.

### Black and Flake8

Black plus Flake8 provide mature formatting and linting. Ruff was selected to
give the small project one fast configuration and command family for both,
while explicit stable rules limit upgrade surprises.

### Pyright

Pyright is capable and fast. Mypy was selected for its established Python
library ecosystem, strict-mode configuration, and granular third-party module
overrides. A future change must demonstrate a concrete benefit and migration
plan rather than run two authoritative type checkers indefinitely.

### `unittest`

The standard-library runner would avoid a test dependency, but pytest's strict
markers, fixtures, parametrization, and coverage integration better support
the planned subprocess, platform, and optional-integration matrix. Pytest stays
a development dependency and does not affect the core runtime contract.

### Nox or Tox

Environment orchestrators can make a large matrix convenient. They are
deferred while the command set is small so CI and contributors can see the
underlying tool invocations directly. They may be added when demonstrated
matrix duplication outweighs the extra abstraction and dependency.

### An immediate lock file

A lock could reproduce one development resolution closely, but a single lock
may not describe every supported Python and operating-system lane and would add
an update process before the tool set stabilizes. The project will first use
reviewed bounds and captured CI evidence, then adopt a lock through a dedicated
issue if concrete resolver drift warrants it.

## Consequences

- Contributors install development groups separately from the package.
- Strict defaults make new code and configuration errors visible early.
- A 100% branch gate requires deliberate tests for every package behavior and
  explicit review of genuinely unreachable paths.
- Offline, controlled unit tests reduce flakiness but require time, environment,
  randomness, and subprocess seams in implementation designs.
- Artifact checks take longer than source-only tests but validate what users
  actually install.
- Direct commands remain understandable; orchestration can be introduced later
  without changing each tool's ownership.

## Implementation follow-ups

Separate issues will:

1. add dependency groups and stable Ruff, strict mypy, pytest, and coverage
   configuration to `pyproject.toml`;
2. add deterministic tests for package metadata, source behavior, and version
   consistency;
3. add maintained artifact inspection and clean-wheel smoke scripts;
4. run quality, supported-Python, operating-system, and integration CI lanes;
   and
5. define dependency-refresh and release validation automation before the
   first publication.

## Primary references

- [Dependency Groups specification](https://packaging.python.org/en/latest/specifications/dependency-groups/)
- [Ruff configuration](https://docs.astral.sh/ruff/configuration/)
- [Ruff formatter](https://docs.astral.sh/ruff/formatter/)
- [Mypy configuration file](https://mypy.readthedocs.io/en/stable/config_file.html)
- [Pytest configuration](https://docs.pytest.org/en/stable/reference/customize.html)
- [Pytest markers](https://docs.pytest.org/en/stable/how-to/mark.html)
- [Coverage.py configuration](https://coverage.readthedocs.io/en/7.16.2/config.html)
- [Coverage.py reporting](https://coverage.readthedocs.io/en/latest/commands/cmd_reporting.html)
- [Build documentation](https://build.pypa.io/en/stable/)
- [Twine documentation](https://twine.readthedocs.io/en/stable/)
