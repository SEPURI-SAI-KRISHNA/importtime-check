# Archived measurement report fixtures

These synthetic, fixed-value files preserve the public version-1 measurement
shape published in `0.1.0a4`. They are not live performance observations or
thresholds. The four valid files follow the worked example in
[ADR 0011](../../docs/design/0011-offline-report-cohorts.md): two complete
before reports and two complete after reports. Their source-byte SHA-256
digests are pinned in `tests/test_report_compatibility.py` to detect silent
fixture rewrites.

`report-v1-duplicate-key.json` intentionally violates strict JSON-key
uniqueness. `report-v2-unsupported.json` intentionally declares a future
version; it must fail with `report-unsupported`, not be interpreted as v1.
Neither file contains private paths, stderr, secrets, or host-specific data.

Do not regenerate these bytes from the current emitter during tests. An
incompatible format change requires a reviewed design and migration decision;
new fixtures should be added rather than silently replacing these v1 files.

`profile-v1.json` is the fixed import-profile example from
[ADR 0013](../../docs/design/0013-import-profile-evidence.md). Its repeated
`json.decoder` rows are separate occurrences. `baseline-schema1.json` freezes
the older baseline shape so profile loading cannot quietly reinterpret it.
Their exact bytes are pinned in the profile artifact tests alongside the
measurement report fixtures. These are synthetic examples, not measurements
or recommended CI thresholds.

`profile-v1-two-target.json` adds fixed `email` and `json` runs for inspection
tests. It deliberately includes repeated names, equal self times, and zero
self time; rankings retain original occurrence numbers and never sum
overlapping cumulative times.

Three archived profile failures stay separate from the valid fixtures:
`profile-v1-duplicate-key.json` repeats a root key, `profile-v1-invalid-event.json`
omits the selected target's unique event, and `profile-v2-unsupported.json`
declares a future version. Their exact bytes are pinned in compatibility tests.
All three must fail closed with safe categories, never become partial evidence
or be reinterpreted as version 1. Do not regenerate them from the current
encoder or replace their bytes silently.
