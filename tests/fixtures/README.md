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
