# A reviewed import-time baseline in CI

This is a small, runnable example for a **consuming project**. It measures the
`packaging` module as a stand-in for your own installed module. The example
files are [pinned requirements](../examples/requirements-importtime.txt), a
[manual candidate workflow](../examples/record-importtime-baseline.yml), and a
[pull-request gate](../examples/check-importtime.yml). Copy them into your
project as described below; do not add these example workflows to this
repository's `.github/workflows/` directory.

The example pins `importtime-check==0.1.0a1`, `packaging==26.3`, CPython 3.11,
the `ubuntu-24.04` runner label, and the action commits. It needs no PyPI
credentials. It is a starting policy, **not** evidence that every GitHub-hosted
runner has equivalent hardware or load. For a dependable, tighter performance
gate, use a controlled runner class or image and investigate ordinary variance
before choosing allowances. A matching five-field identity cannot detect
dependency changes, Python patch changes, CPU contention, or host differences.

## Bootstrap the policy

1. Copy `docs/examples/requirements-importtime.txt` to
   `ci/requirements-importtime.txt` in your project. Replace the demonstration
   `packaging` pin with a complete, reviewed lock of your target's runtime
   dependencies; include the target package itself. Keep the tool pin exact.
   If the target is the checked-out project, install its built wheel in both
   workflows after the locked dependencies, rather than relying on the current
   directory as an import location. The child uses Python isolated mode and
   does not import modules merely because they are in the checkout.
2. Copy `docs/examples/record-importtime-baseline.yml` to
   `.github/workflows/record-importtime-baseline.yml`. Change its `--module`
   argument to your installed target and choose initial allowances based on
   repeated observations. Commit this manual workflow and the lock file to the
   default branch. GitHub requires a manually dispatched workflow to exist on
   the default branch before it can be dispatched.
3. In GitHub Actions, run **Import-time baseline candidate**. It installs the
   exact requirements, records seven fresh samples after one warmup on its
   `ubuntu-24.04` runner, and uploads `importtime-baseline-candidate.json` as
   an artifact. Download that artifact, inspect its identity, module names,
   sampling settings, median, and allowances, then place the JSON at
   `ci/importtime-baseline.json`. Do not accept it just because a run succeeded.
4. Review and commit the baseline file like source code. Copy
   `docs/examples/check-importtime.yml` to
   `.github/workflows/check-importtime.yml` in the same change or a later one.
   Make the check required only after the file and gate are present. Both
   workflows must install the same locked target environment, select the same
   Python minor version, runner class, module list, and `--profile`. For a
   different OS, architecture, dependency set, or deployment context, maintain
   a separate baseline/profile; do not reuse the candidate from this runner.

The candidate workflow writes only to an ephemeral artifact; it never updates
the committed policy. The check workflow reads the committed baseline and
passes an explicit `--module` to catch target-set drift. It does not create or
refresh a baseline. The example's `1000` microsecond and `25` percent
allowances are illustrative, not recommended budgets for every project. A
regression is reported only when the increase exceeds **both** allowances.
Tune them through measured variance and a reviewed PR, not a failing CI run's
single timing.

To check command syntax locally with the published package, a disposable
standard-library target is enough; **do not commit this local baseline for a
different CI runner**:

```console
python -m pip install --pre importtime-check==0.1.0a1
importtime-check baseline record --output importtime-local.json --module json --warmups 0 --samples 1 --max-increase-us 1000000 --max-increase-percent 100 --profile local-smoke
importtime-check baseline show --file importtime-local.json
importtime-check check --baseline importtime-local.json --module json --profile local-smoke
```

## When the gate fails

- Exit `0` means all requested targets passed. Exit `1` means at least one
  exceeded both reviewed allowances; inspect the medians, samples, top imports,
  and recent dependency or code changes. Do not automatically raise thresholds
  or overwrite the baseline. Exit `2` is invalid input or an operational or
  non-comparable state, **not** a performance verdict. `--format json` emits a
  schema-1 report for these outcomes, except argument-syntax errors.
- For an environment mismatch, check the selected CPython version, runner
  class, architecture, and `--profile` against the baseline. For a target-set
  mismatch, compare explicit `--module` selections with the baseline targets.
  `baseline show --file ci/importtime-baseline.json` displays the stored
  identity and policy. The pending `0.1.0a2` diagnostics name differing
  identity fields (showing only safe Python major.minor values) and sorted
  missing/stale targets; `0.1.0a1` has less detailed messages. Correct a
  configuration mistake; if the change is intentional, record and review a
  new baseline in the new environment. Do not compare an unrelated machine
  merely because the command accepts it.
- A change only to observed medians can be proposed by
  `baseline refresh --file ci/importtime-baseline.json --replace` **after**
  upgrading to a release that includes refresh. It retains target names,
  identity, sampling, and per-target allowances; inspect the file diff before
  accepting it. A target, identity, sampling, or allowance change requires
  `baseline record --replace` or an explicitly reviewed policy edit. The
  published `0.1.0a1` pin in this example does **not** have `refresh` or the
  newer field-level mismatch messages; those are planned for `0.1.0a2`.

The optional pytest adapter is another way to run the same gate. Pin the
matching extra and pytest version in the lock file, then explicitly load
`-p importtime_check.pytest_plugin` and pass
`--importtime-baseline ci/importtime-baseline.json`,
`--importtime-module packaging`, and the matching `--importtime-profile`.
Invalid configuration is a pytest usage error before tests; a regression or
measurement error fails an otherwise successful session. Do not run both the
CLI gate and pytest adapter unless two checks are intentional.

See the [baseline comparison contract](../design/0007-regression-and-integration-contract.md)
and [refresh/diagnostic contract](../design/0008-safe-baseline-refresh-and-diagnostics.md)
for exact semantics. GitHub documents the [default-branch requirement for
manual workflows](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)
and [downloading workflow artifacts](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts).
