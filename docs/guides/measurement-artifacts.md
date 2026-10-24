# Collect reviewable import-time measurements

This guide is for a **consuming project** that wants to observe several
installed Python modules before choosing any regression budget. The example
measures `packaging` and `packaging.version`, writes three separate versioned
JSON reports, and uploads them for human review. It does **not** gate pull
requests, create or refresh a baseline, compare machines, or decide whether
performance regressed.

The [manual workflow](../examples/collect-importtime-measurement.yml) and
[exact requirements](../examples/requirements-measurement.txt) target
`importtime-check==0.1.0a4`, `packaging==26.3`, CPython 3.11, and the
`ubuntu-24.04` runner label. The published `0.1.0a4` wheel collects these
reports; the `report summarize` and `report compare` commands below are
development features planned for `0.2.0a1`, not yet in that PyPI release.

## Try the report locally

Install the selected targets and a suitable `importtime-check` wheel into the
same clean environment. The example targets are installed by the exact
`packaging==26.3` pin; the example requirements file also pins the published
collector:

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

## Collect complete runs before and after a change

The [manual workflow](../examples/collect-importtime-measurement.yml) runs
the same two-target `measure --format json` command three times. Each command
performs one warmup and seven recorded child-process imports **per target**;
the three resulting files are separate, complete reports, not seven reports
and not a pooled sample. The workflow checks the shape of all three files
before uploading one artifact containing them. A failed measurement prevents
upload. Run it once for a pinned "before" revision and again for a pinned
"after" installed target revision on the same runner class, with a complete
reviewed dependency lock for each revision. The fixed `packaging==26.3`
demonstration lock does **not** change between dispatches by itself: two
dispatches with that same lock are repeat observations of one installation,
not evidence of a code-change effect. For a real before/after review,
replace the target package pin or built target wheel deliberately on each
side, then retain both exact locks and resolved source revisions. Download
both artifacts and keep their three files under separate `before/` and
`after/` directories so their identical uploaded names cannot overwrite
one another. Save the workflow run URLs, source revisions, lockfile, runner
image, and Python patch version beside them.

One workflow dispatch gives three nearby observations, not independent
machines or proof of a stable distribution. Repeat dispatches or use a
controlled runner if host noise matters. Check for installation drift,
contention, unusually slow runs, and import side effects before treating
the cohorts as comparable. Do not select a threshold from one favorable run.

## Summarize a controlled cohort

The `report summarize` command is available in a clean wheel built from the
reviewed development source for `0.2.0a1`; the published `0.1.0a4` collector
above does not include it. Keep each downloaded three-file set complete and
use a separate environment with that development wheel for offline analysis.
For the first artifact, run:

```console
importtime-check report summarize --file before/importtime-measurement-1.json --file before/importtime-measurement-2.json --file before/importtime-measurement-3.json --runner-context ubuntu24-py311 --install-context build-before
importtime-check report summarize --file before/importtime-measurement-1.json --file before/importtime-measurement-2.json --file before/importtime-measurement-3.json --runner-context ubuntu24-py311 --install-context build-before --format json
```

These context labels are caller assertions, not verified environment hashes.
Retain the exact runner definition, lockfile, and revision beside the source
artifacts. `build-before` identifies the intended installed revision, not a
value extracted from the JSON; if both sets have identical installed pins,
use the same installation label. Run the same command on the `after/` files
with `--install-context build-after` only for an intended installed change.
The command validates every file and checks matching reported identity,
sampling, and target set before printing; invalid input exits `2` with empty
stdout. It shows each target's observed median of complete-run
medians, range, and spread, but does not decide whether a change regressed or
write a baseline. The JSON has its own `analysis_type` and
`analysis_version`; it is not a measurement or baseline document. Read the
three `run_medians_us` values, `min_us`, `max_us`, and `spread_us` for **each**
target. A large spread relative to the observed shift is a reason to
investigate and collect more evidence, not to delete a slow run. This is a
single-cohort view, not an approved performance gate.

The development Python API can also compare two such reviewed cohorts:

```python
from importtime_check import (
    compare_report_cohorts,
    load_measurement_report,
    summarize_measurement_reports,
)

before = summarize_measurement_reports(
    tuple(
        load_measurement_report(f"before/importtime-measurement-{n}.json")
        for n in (1, 2, 3)
    ),
    runner_context="ubuntu24-py311",
    install_context="build-before",
)
after = summarize_measurement_reports(
    tuple(
        load_measurement_report(f"after/importtime-measurement-{n}.json")
        for n in (1, 2, 3)
    ),
    runner_context="ubuntu24-py311",
    install_context="build-after",
)
comparison = compare_report_cohorts(before, after)
for module, change in comparison.changes.items():
    print(
        module,
        change.change_us,
        change.change_percent,
        before.targets[module].spread_us,
        after.targets[module].spread_us,
    )
```

The comparison retains both complete cohorts, including their ranges and
source digests. It requires matching runner context, reported identity,
sampling, and target set; invalid inputs raise `MeasurementReportError` with
`cohort-invalid` or `cohort-mismatch`. Different installation labels are
allowed for the intended change. Percentage change is `None` when the before
median is zero, and may round to `0.00` for a nonzero microsecond shift; read
the signed `change_us` too. This API has no verdict and does not write a
baseline.

The corresponding development CLI compares the same six files without
writing an analysis file or changing baseline policy:

```console
importtime-check report compare --before-file before/importtime-measurement-1.json --before-file before/importtime-measurement-2.json --before-file before/importtime-measurement-3.json --after-file after/importtime-measurement-1.json --after-file after/importtime-measurement-2.json --after-file after/importtime-measurement-3.json --runner-context ubuntu24-py311 --before-install-context build-before --after-install-context build-after
importtime-check report compare --before-file before/importtime-measurement-1.json --before-file before/importtime-measurement-2.json --before-file before/importtime-measurement-3.json --after-file after/importtime-measurement-1.json --after-file after/importtime-measurement-2.json --after-file after/importtime-measurement-3.json --runner-context ubuntu24-py311 --before-install-context build-before --after-install-context build-after --format json
```

Its text output shows signed microseconds, percentage or `n/a`, and both
observed spreads. Versioned JSON embeds both complete cohort summaries and
per-target changes. Invalid or non-comparable input exits `2` with empty
stdout; success exits `0` without a regression verdict. The published
`0.1.0a4` package does not include this development command.

If either command reports `cohort-mismatch`, read the named fields: for
example, `sampling.samples`, `environment.python`, or `targets`. Check that
the files really came from one intended installation and sampling setup;
do not edit JSON to make them match. A mismatch between sides can also mean
the runner class or target set changed. `report-invalid` means the input is
not a valid v1 measurement, while `report-unsupported` means its version is
not supported. `cohort-invalid` includes missing independent reports or
duplicate report bytes. Normal diagnostics identify a side and file position
without printing private paths. Recollect or separate non-comparable runs;
do not interpret exit `2` as a performance regression.

Even a valid comparison only describes a shift. A positive `change_us` can
be host noise; a small spread does not prove identical dependencies, Python
patch versions, hardware, or host load. The safe four-field identity and
caller labels cannot verify those omitted conditions. Only after reviewing
repeat-run evidence should you choose allowances and create a **candidate**
baseline with the [baseline workflow](ci-baselines.md). That candidate still
needs a PR review before its JSON becomes an approved CI gate. Neither
`report summarize` nor `report compare` changes or approves baseline policy.

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
   installs the pins, runs `measure --format json` three times, checks each
   report's complete target set and sampling shape, then uploads
   `.tmp/importtime-measurement-{1,2,3}.json` only after all steps succeed.
   Download the artifact and review each environment, sample array, and
   median alongside the exact dependency and runner versions used for that
   run. Preserve the original report bytes for source-digest review.

This example is intentionally **manual**: it has no `pull_request` trigger or
required status check, does not read or write `ci/importtime-baseline.json`,
and contains no `baseline record`, `baseline refresh`, or `check` command.
Successful upload means three complete observations were collected, not that an
allowance was approved. The `actions/upload-artifact` step uploads only the
report files; the package itself performs no network upload.

When the team is ready to gate regressions, use the separate
[reviewed baseline guide](ci-baselines.md). Choose allowances after
investigating repeat-run variance, record candidate policy in a controlled
environment, and review and commit it through a PR. Never automatically
rewrite approved baseline policy from an observation-only workflow.
