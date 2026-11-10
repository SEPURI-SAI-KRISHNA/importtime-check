# Review a baseline proposal before making it CI policy

`baseline propose` turns a reviewed cohort of complete measurement reports
into a **candidate**, not an approved regression budget. The candidate uses
ordinary schema-1 baseline JSON: there is no approval flag in the file. The
boundary is your repository review and the path your required check reads.
Never point a required check or pytest gate at a downloaded candidate.

This workflow needs `importtime-check==0.2.0a2`. Until it is published, test
with a clean wheel built from the reviewed source; do not claim that the
published `0.2.0a1` wheel already has `baseline propose`. The example target
environment uses `packaging==26.3`, CPython 3.11, and `ubuntu-24.04`. Replace
those pins with a complete reviewed lock, interpreter, and runner for your
actual project. The example allowances are syntax illustrations, **not**
recommended thresholds for GitHub-hosted runners.

Until release preparation changes the source version, a locally built wheel
may still report `0.2.0a1` despite containing unreleased proposal code. Use it
only for local review or CI verification; do not publish it or confuse it
with the `0.2.0a1` files already on PyPI.

## 1. Retain complete observations

The [manual proposal workflow](../examples/propose-importtime-baseline.yml)
collects three complete reports for `packaging` and `packaging.version`, then
uploads a candidate and a separate explanation. Copy that workflow to your
consuming project's `.github/workflows/` directory and copy its
[requirements file](../examples/requirements-candidate.txt) to
`ci/requirements-candidate.txt`; review and commit both before dispatching it.
Its `workflow_dispatch` trigger, read-only token, and upload path do not
change your approved baseline. The separate
[required check example](../examples/check-importtime.yml) continues to read
only `ci/importtime-baseline.json`.

For a policy review, also retain the **exact source report bytes** from a
controlled collection, together with the workflow run URL, source revision,
complete dependency lock, Python patch level, runner image, and relevant host
conditions. The proposal workflow intentionally uploads only the candidate
and explanation, not its temporary report files. Its source digests therefore
cannot, by themselves, let a reviewer inspect those exact observations. If
you need an auditable proposal, collect and retain reports with the
[measurement artifact workflow](../examples/collect-importtime-measurement.yml)
or an equivalent controlled process, then run `baseline propose` on **those
same saved bytes**. A separate collection with different digests is not the
candidate's source evidence. Do not approve a candidate when its source
reports cannot be traced and inspected.

For a locally retained three-file cohort, inspect its target set, identity,
sampling, individual samples, run medians, and spread before choosing policy:

```console
importtime-check report summarize --file reports/run-1.json --file reports/run-2.json --file reports/run-3.json --runner-context gh-ubuntu-24.04 --install-context packaging-26.3
```

The context labels are human assertions, not verified hashes or attestations.
The report identity omits dependency versions, Python patch version, runner
image, hardware, and host load. Same reported identity and a valid cohort do
not establish independent runs or statistical significance. If conditions
changed, split the runs or recollect; do not edit JSON or discard a slow run
to force comparability.

## 2. Choose allowances and create a new candidate

Choose a deliberate profile for the intended gate environment and one
absolute/percentage allowance for **each** target. Reuse the exact report
files inspected above. This example writes a new candidate and prints a
separate explanation; replace the illustrative budgets after investigating
normal variation:

```console
importtime-check baseline propose --file reports/run-1.json --file reports/run-2.json --file reports/run-3.json --runner-context gh-ubuntu-24.04 --install-context packaging-26.3 --profile gh-ubuntu-24.04 --budget packaging=1000,25 --budget packaging.version=2000,30 --output candidate/importtime-baseline-candidate.json --explain
```

Create the `candidate/` directory first. The candidate file must **not**
already exist: proposal has no `--replace` option. Keep the original reports,
the explanation, and the candidate together for review. The explanation
lists sorted source SHA-256 digests, observed per-target ranges and spread,
the chosen allowances, and the candidate-file digest. Verify the source
digests against the retained bytes and record why the profile and each
allowance were chosen. A digest identifies bytes, not their origin or
comparability. Do not add provenance or approval metadata to schema 1.

If an approved baseline already exists, add
`--compare-baseline ci/importtime-baseline.json` to the proposal command
**before** creating a new output path. The explanation then names changed
identity, sampling, target, median, and allowance fields. An invalid old
baseline fails the proposal; the command never imports old allowances or
modifies old policy. Compare the diff and retain the old approved file until
a separate PR is reviewed.

## 3. Promote policy only through a reviewed PR

Create a separate approval PR in the consuming project. Include the exact
candidate JSON as the proposed change to `ci/importtime-baseline.json`, or
show its full diff against the currently committed file. Attach or link the
source reports and explanation, the runner/dependency evidence, and the
reason for each budget. Review the identity, target set, sampling, observed
medians, allowances, and any change from existing policy. The approver can
reject the proposal and request more observations; a successful candidate
workflow is not approval.

Only after that PR merges should the required `check` workflow (or an
explicitly loaded pytest plugin) use the committed `ci/importtime-baseline.json`.
Keep its tool/target lock, interpreter minor version, runner class, profile,
and exact module selection aligned with the approved policy. The proposal
workflow does not commit, open a PR, change the required check, or select a
budget. `check` and pytest never learn thresholds from raw reports or the
explanation.

## Deterministic two-target rehearsal

The repository's archived v1 files are **synthetic fixtures**, not real
performance evidence. After installing a clean wheel built from this source,
run this command from the repository root to rehearse the offline two-target
proposal without importing the targets or depending on your host identity:

```console
importtime-check baseline propose --file tests/fixtures/report-v1-before-1.json --file tests/fixtures/report-v1-before-2.json --runner-context archived-example --install-context synthetic-fixtures --profile example-only --budget email=3,15 --budget json=8,10 --output .tmp/fixture-candidate.json --explain
```

Create `.tmp` first and choose a new output filename for each rehearsal. The
candidate has `email` median `11 us`, `json` median `42 us`, and exactly the
two explicit allowance pairs above; the explanation stays outside the JSON.
Do **not** commit this synthetic candidate or run `check` against it: its
Linux/CPython 3.11 identity may differ from your machine and it is not an
approved policy. This rehearsal verifies the command route; it cannot
validate a real CI budget.

## Failure and alpha upgrade behavior

An unreadable, malformed, future-version, duplicate, or non-comparable report;
a missing/extra/duplicate/invalid budget; a bad profile; an invalid old
baseline; or an existing output path stops candidate creation. Expected
errors exit `2` with no candidate or partial JSON. If redirecting the
explanation to a file, the shell can leave an empty file on failure; check
the command exit status and discard that file. Neither failure nor success
changes the approved baseline. Never use `baseline refresh --replace` as an
automatic workaround for a failed proposal or gate.

Existing v1 measurement reports from `0.1.0a4` remain valid inputs; the
offline `report summarize` command arrived in `0.2.0a1`. Existing schema-1
approved baselines from the `0.1.x` alphas or `0.2.0a1` need no format
migration. Their `check`/pytest thresholds and exit codes are unchanged.
`0.2.0a2` adds the proposal and explanation route; it does not rewrite
policy or make earlier direct `baseline record` guidance invalid. A
candidate's schema matches the approved format, but promotion still requires
the separate human-reviewed PR and deliberate committed path.
