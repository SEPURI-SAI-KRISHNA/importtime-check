# Collect and inspect import-profile evidence

Import profiles are opt-in diagnostic evidence for investigating which import
rows appeared in **one selected run**. They do not set a budget, approve a
baseline, or return a regression verdict. This guide targets `0.3.0a1` and
the reviewed source preparing that release. Until `0.3.0a1` is published, use
a clean wheel built from the reviewed source; the current `0.2.0a2` PyPI wheel
does not contain these profile APIs or `profile show`.

After publication, pin the tool in the consuming project's reviewed dependency
set alongside its target dependencies and interpreter, for example:

```console
python -m pip install "importtime-check==0.3.0a1"
```

Do not run that PyPI command before publication or mistake a development wheel
for the published release. The examples below assume `email` and `json` are
available in the selected CPython environment. For a real project, install
the exact target dependency lock in the same environment, on a controlled
runner, and retain its revision, Python patch level, runner image, and relevant
host context separately. CPython 3.11–3.14 are tested.

## Two-target collection and selected-run review

Run this from a clean environment with the pinned tool installed. It performs
one fresh isolated child import for each target, produces a version-1 profile,
and writes only the canonical encoded artifact. The zero-warmup, one-sample
settings keep the example quick; they are **not** a reliable budget-estimation
policy. Production review can choose more runs within the documented limits.

```console
python -I -c "from pathlib import Path; from importtime_check import capture_import_profile, encode_import_profile; profile = capture_import_profile(('email', 'json'), warmups=0, samples=1); Path('profile.json').write_bytes(encode_import_profile(profile))"
importtime-check profile show --file profile.json --target json --phase sample --run 1 --limit 5 --format json
```

`capture_import_profile` sorts distinct targets by exact name and retains
ordered warmup/sample runs. It never imports selected targets into the caller.
It fails the entire request on a failed target/run or a profile resource limit;
there is no partial artifact. `profile show` requires an explicit target,
phase, and one-based run number. To inspect `email`, change only `--target`.
To inspect a different actual run, select its recorded phase and number; the
tool does not invent a median or representative trace. The command is
read-only; an invalid file or selection exits 2 with empty stdout.

The output identifies the exact source-file SHA-256, safe interpreter identity,
selected run, original occurrence numbers, and separate self-time and
cumulative-time rankings. A repeated module name represents separate import
occurrences. Self time excludes nested imports; cumulative time includes them
and **overlaps across nested rows**, so do not sum cumulative values or read a
ranking as a call graph. A slow row is an observation, not proof that the
module caused a regression. See the [profile design record](../design/0013-import-profile-evidence.md)
for the exact schema and limits.

## Review and privacy boundaries

Import timing is sensitive to host load, dependency changes, interpreter
configuration, and Python patch level. Compare only like-for-like controlled
conditions; a matching artifact identity alone does not establish that. CPython
warns that `-X importtime` output can be unreliable in multithreaded programs.
This tool accepts numeric rows, not Python 3.14 cached-row output from
`-X importtime=2`. It reports CPython import diagnostics, not whole-process
startup time or causality.

The artifact omits raw stderr, working-directory and interpreter paths,
environment variables, and timestamps. Module names can still reveal project
structure. Inspect an artifact before sharing it, and do not upload it
automatically. A source digest identifies exact bytes, not origin or host
comparability. Keep the original file and separate runner/dependency evidence
when it informs a review. The existing version-1 measurement report and
schema-1 baseline are different formats and remain the only inputs to their
respective report and policy paths; `profile show` cannot approve or change a
baseline. See the [measurement artifact guide](measurement-artifacts.md) for
report collection and the [CI baseline guide](ci-baselines.md) for reviewed
regression policy.
