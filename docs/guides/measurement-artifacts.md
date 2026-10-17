# Collect reviewable import-time measurements

This guide is for a **consuming project** that wants to observe several
installed Python modules before choosing any regression budget. The example
measures `packaging` and `packaging.version`, writes one versioned JSON
report, and uploads it for human review. It does **not** gate pull requests,
create or refresh a baseline, compare machines, or decide whether performance
regressed.

The [manual workflow](../examples/collect-importtime-measurement.yml) and
[exact requirements](../examples/requirements-measurement.txt) target
`importtime-check==0.1.0a4`, `packaging==26.3`, CPython 3.11, and the
`ubuntu-24.04` runner label. The `0.1.0a4` PyPI pin becomes installable only
after that release is published. Before publication, test the behavior with a
clean wheel built from the reviewed source, not the published `0.1.0a3`
package, which lacks multi-target `measure` JSON.

## Try the report locally

Install the selected targets and a suitable `importtime-check` wheel into the
same clean environment. The example targets are installed by the exact
`packaging==26.3` pin. After `0.1.0a4` is published, the example requirements
file installs the exact tool pin as well:

```console
python -m pip install --requirement ci/requirements-measurement.txt
python -m pip check
importtime-check measure --module packaging --module packaging.version --warmups 1 --samples 7 --format json
```

The library equivalent returns a complete tuple of immutable sample sets in
sorted module order. It neither probes safe JSON identity nor writes a report;
the CLI adds those presentation steps:

```python
from importtime_check import sample_imports

for target in sample_imports(("packaging.version", "packaging"), warmups=1, samples=7):
    print(target.module, target.median_cumulative_us)
```

Every warmup and recorded sample imports one installed target in a fresh,
isolated child interpreter. The per-target `warmups_us` and `samples_us`
arrays retain run order. `upper_median_us` is one **observed** cumulative
import time from recorded samples; warmups are excluded. All timings are
integer microseconds from CPython's `-X importtime`, not whole-process startup
time. A later-target error exits with code `2` and writes no partial JSON to
stdout. If redirecting to a file, check the exit status before keeping or
uploading it; a shell can leave an empty redirected file on failure.

Successful JSON has `report_type: "measurement"` and `report_version: 1`.
Consumers should check both. `environment` includes only implementation,
Python major.minor, platform, and machine. It intentionally omits executable
and working-directory paths, Python patch version, dependencies, runner
image, host load, and any profile label. The report has no approved budgets,
baseline medians, regression status, or confidence interval. Do not pass it
to `check` as if it were baseline schema 1.

To judge ordinary variation, collect several complete reports on the same
controlled runner class with the same interpreter, installed dependency set,
target list, and sampling settings. Inspect each target's recorded sample
spread and upper medians across those runs, including unusually slow or
unstable runs. A matching four-field report identity does **not** prove
comparability: Python patch level, dependency updates, CPU contention,
hardware, runner image, and import side effects can change timings. A
single report cannot justify a tight threshold or a cross-host comparison.

## Summarize a controlled cohort

The `report summarize` command is available in the development wheel for
`0.2.0a1` (and in that release once published); the `0.1.0a4` pin used by
the collection workflow above does not include it. Download at least two
complete JSON reports from the same controlled runner class and intended
installed revision/dependency state, then run:

```console
importtime-check report summarize --file run-1.json --file run-2.json --runner-context ubuntu24-py311 --install-context build-before
importtime-check report summarize --file run-1.json --file run-2.json --runner-context ubuntu24-py311 --install-context build-before --format json
```

These context labels are caller assertions, not verified environment hashes.
Retain the exact runner definition, lockfile, and revision beside the source
artifacts. The command validates every file and checks matching reported
identity, sampling, and target set before printing; invalid input exits `2`
with empty stdout. It shows each target's observed median of complete-run
medians, range, and spread, but does not decide whether a change regressed or
write a baseline. The JSON has its own `analysis_type` and
`analysis_version`; it is not a measurement or baseline document. This is a
single-cohort view; before/after comparison is tracked separately.

## Upload an observation-only CI artifact

1. Copy `docs/examples/requirements-measurement.txt` to
   `ci/requirements-measurement.txt` in the consuming project. Replace the
   demonstration `packaging` pin with a reviewed lock of the actual targets
   and their dependencies; include the target package itself. Keep the
   `importtime-check` pin exact. If measuring the checked-out project,
   install its built wheel into this environment instead of assuming the
   source directory is importable in Python's isolated mode.
2. Copy `docs/examples/collect-importtime-measurement.yml` to
   `.github/workflows/collect-importtime-measurement.yml`. Replace its two
   `--module` values and JSON target-set assertion with the same installed
   targets. Commit the workflow and requirements file to the default branch;
   a `workflow_dispatch` workflow must exist there before manual dispatch.
3. Run **Import-time measurement artifact** from GitHub Actions. The workflow
   installs the pins, runs `measure --format json`, checks the complete
   target set and sampling shape, then uploads
   `.tmp/importtime-measurement.json` only after those steps succeed.
   Download the artifact and review its environment, sample arrays, and
   medians alongside the exact dependency and runner versions used for that
   run. Retain separate reports if repeating the measurement.

This example is intentionally **manual**: it has no `pull_request` trigger or
required status check, does not read or write `ci/importtime-baseline.json`,
and contains no `baseline record`, `baseline refresh`, or `check` command.
Successful upload means a complete observation was collected, not that an
allowance was approved. The `actions/upload-artifact` step uploads only the
report file; the package itself performs no network upload.

When the team is ready to gate regressions, use the separate
[reviewed baseline guide](ci-baselines.md). Choose allowances after
investigating repeat-run variance, record candidate policy in a controlled
environment, and review and commit it through a PR. Never automatically
rewrite approved baseline policy from an observation-only workflow.
