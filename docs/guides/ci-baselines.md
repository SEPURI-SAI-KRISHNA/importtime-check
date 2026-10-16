# A reviewed import-time baseline in CI

To collect several observations **without** approving a budget or gating a
pull request, use the separate [measurement artifact guide](measurement-artifacts.md).
The steps below create and check reviewed baseline policy.

This is a small, runnable example for a **consuming project**. It measures the
`packaging` and `packaging.version` modules as stand-ins for two of your own
installed modules. The example files are
[pinned requirements](../examples/requirements-importtime.txt), a
[manual candidate workflow](../examples/record-importtime-baseline.yml), and a
[pull-request gate](../examples/check-importtime.yml). Copy them into your
project as described below; do not add these example workflows to this
repository's `.github/workflows/` directory.

The release example pins `importtime-check==0.1.0a3`, `packaging==26.3`,
CPython 3.11, the `ubuntu-24.04` runner label, and the action commits. It needs no PyPI
credentials. It is a starting policy, **not** evidence that every GitHub-hosted
runner has equivalent hardware or load. For a dependable, tighter performance
gate, use a controlled runner class or image and investigate ordinary variance
before choosing allowances. A matching five-field identity cannot detect
dependency changes, Python patch changes, CPU contention, or host differences.
The `0.1.0a3` pin becomes installable from PyPI only after publication. Before
then, validate these commands against a wheel built from the reviewed source.

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
   `.github/workflows/record-importtime-baseline.yml`. Change its two
   `--module` arguments to your installed targets and choose each initial
   `--budget` allowance based on repeated observations. Commit this manual
   workflow and the lock file to the
   default branch. GitHub requires a manually dispatched workflow to exist on
   the default branch before it can be dispatched.
3. In GitHub Actions, run **Import-time baseline candidate**. It installs the
   exact requirements, records seven fresh samples after one warmup on its
   `ubuntu-24.04` runner, and uploads `importtime-baseline-candidate.json` as
   an artifact. Download that artifact, inspect its identity, module names,
   sampling settings, both medians, and each allowance, then place the JSON at
   `ci/importtime-baseline.json`. Do not accept it just because a run succeeded.
4. Review and commit the baseline file like source code. Copy
   `docs/examples/check-importtime.yml` to
   `.github/workflows/check-importtime.yml` in the same change or a later one.
   Make the check required only after the file and gate are present. Both
   workflows must install the same locked target environment, select the same
   Python minor version, runner class, exact module list, and `--profile`. For a
   different OS, architecture, dependency set, or deployment context, maintain
   a separate baseline/profile; do not reuse the candidate from this runner.

The candidate workflow writes only to an ephemeral artifact; it never updates
the committed policy. The check workflow reads the committed baseline and
passes both explicit `--module` selections to catch target-set drift. It does
not create or refresh a baseline. The candidate records this exact policy:

| Target | Allowed increase (us) | Allowed increase (%) |
| --- | ---: | ---: |
| `packaging` | 1000 | 25 |
| `packaging.version` | 2000 | 30 |

These allowances are illustrative, not recommended budgets for every project. A
regression is reported only when the increase exceeds **both** allowances.
Tune them through measured variance and a reviewed PR, not a failing CI run's
single timing.

To check that the old common-allowance flags still work with `0.1.0a3`, a
disposable standard-library target is enough; **do not commit this local
baseline for a different CI runner**:

```console
python -m pip install --pre importtime-check==0.1.0a3
importtime-check baseline record --output importtime-common-local.json --module json --warmups 0 --samples 1 --max-increase-us 1000000 --max-increase-percent 100 --profile local-smoke
importtime-check baseline show --file importtime-common-local.json
importtime-check check --baseline importtime-common-local.json --module json --profile local-smoke
```

## Record and review a two-module policy

Version `0.1.0a3` accepts one repeatable `--budget MODULE=US,PERCENT` entry per
explicit `--module`. Install the exact release above after publication, or use
a wheel built from this reviewed checkout beforehand. `email` and `json` are
standard-library stand-ins for two modules installed in the interpreter used
by your actual project. Run these commands on one machine; do not commit this
local baseline as a CI policy:

```console
importtime-check baseline record --output importtime-local.json --module email --module json --budget email=150,20 --budget json=25,10 --warmups 1 --samples 7 --profile local-review
importtime-check baseline show --file importtime-local.json
importtime-check check --baseline importtime-local.json --module email --module json --profile local-review
importtime-check baseline refresh --file importtime-local.json --replace --profile local-review
importtime-check baseline show --file importtime-local.json
```

The resulting schema-1 policy stores these exact, normalized allowances;
the recorded medians depend on the observations, not on the budgets:

| Target | Allowed increase (us) | Allowed increase (%) |
| --- | ---: | ---: |
| `email` | 150 | 20 |
| `json` | 25 | 10 |

These numbers illustrate syntax only; they are **not** recommended CI
thresholds. A later `check` can exit `1` if either target increases beyond
both of its own allowances. `refresh --replace` measures the same targets with
the stored sampling policy and updates only medians, retaining the table's
allowances. It does not run as part of `check` or pytest. To change a target,
identity, sampling policy, or allowance deliberately, re-record with
`baseline record --replace` and review every changed field in the diff.
Budget mode requires exactly one entry for each selected module and cannot be
mixed with the old common-allowance flags; incomplete or ambiguous input is
rejected before target imports or baseline writing.

The included consuming-project workflows pin `0.1.0a3`: the manual candidate
passes both `--module` selections and their two `--budget` entries; the PR
gate passes the same explicit module list but no budgets. Keep the same
installed dependency set, Python minor version, runner class,
and `--profile` for recording and checking. Upload the candidate as an
artifact, review its identity, both medians, sampling, and **each** allowance,
then commit the approved JSON through a PR. Neither workflow should rewrite
the approved baseline automatically. Even with identical recorded identity,
host load and dependency changes can invalidate a comparison; measure normal
variance on a controlled runner before selecting a useful budget.

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
  identity and policy. Since `0.1.0a2`, diagnostics name differing identity
  fields (showing only safe Python major.minor values) and sorted
  missing/stale targets. Correct a configuration mistake; if the change is
  intentional, record and review a
  new baseline in the new environment. Do not compare an unrelated machine
  merely because the command accepts it.
- A change only to observed medians can be proposed by
  `baseline refresh --file ci/importtime-baseline.json --replace`. Available
  since `0.1.0a2`, it retains target names, identity, sampling, and per-target
  allowances; inspect the file diff before
  accepting it. A target, identity, sampling, or allowance change requires
  `baseline record --replace` or an explicitly reviewed policy edit. The
  first alpha (`0.1.0a1`) does **not** have `refresh` or the newer field-level
  mismatch messages.

The optional pytest adapter is another way to run the same gate. Pin the
matching extra and pytest version in the lock file, then explicitly load
`-p importtime_check.pytest_plugin` and pass
`--importtime-baseline ci/importtime-baseline.json`,
`--importtime-module packaging`, `--importtime-module packaging.version`,
and the matching `--importtime-profile`.
Invalid configuration is a pytest usage error before tests; a regression or
measurement error fails an otherwise successful session. Do not run both the
CLI gate and pytest adapter unless two checks are intentional.

See the [baseline comparison contract](../design/0007-regression-and-integration-contract.md)
and [refresh/diagnostic contract](../design/0008-safe-baseline-refresh-and-diagnostics.md)
for exact semantics. GitHub documents the [default-branch requirement for
manual workflows](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)
and [downloading workflow artifacts](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts).
