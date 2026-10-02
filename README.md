# importtime-check

`importtime-check` is a planned CI gate for detecting regressions in Python
import time. It will measure imports in clean subprocesses, compare results
with deterministic baselines, and report actionable diagnostics when startup
performance regresses.

## Project status

This project is in early development and has not been released. Installation
instructions and a stable public API are not available yet.

The first planned release is `0.1.0a1`. Python 3.11 or newer will be required.

## Planned focus

- Repeatable import-time measurements with noise control.
- Deterministic, reviewable baseline files.
- Absolute and relative regression thresholds for CI.
- Import-chain diagnostics for finding newly introduced heavy imports.
- A standard-library-only core with pytest support as an optional integration.

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) and
[NOTICE](NOTICE).

This is an independent open-source project. It is not affiliated with or
endorsed by the Apache Software Foundation.
