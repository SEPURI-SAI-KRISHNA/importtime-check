# 0001: Packaging and compatibility contract

- Status: Accepted
- Acceptance: merge of the pull request that adds this record
- Decision date: 2026-10-02
- Decision issue: [#3](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/3)
- Owners: `importtime-check` maintainers

## Context

`importtime-check` needs an installable command-line tool and Python API, but
packaging choices can accidentally create several sources of truth, import
code from the checkout instead of the built artifact, pull optional frameworks
into the core installation, or promise compatibility that is not tested.

This project also measures import performance. Resolving the package version
through installed-distribution metadata during `import importtime_check` would
add avoidable work to the behavior being measured. The runtime version must be
available through a small module with no I/O and no optional imports.

At the time of this decision, Python 3.10 reached end of life on 2026-10-01,
and Python 3.9 and earlier were already unsupported upstream. Beginning a new
package on those versions would create an immediate legacy maintenance and
security burden.

## Decision

### Project identities

The distribution name is `importtime-check`. The import package name is
`importtime_check`. Documentation and packaging metadata must keep this
distinction explicit.

### Build metadata and backend

The project will use a single `pyproject.toml` with standardized
`[build-system]` and `[project]` tables. Hatchling is the PEP 517 build backend.
Its build requirement will start at `hatchling>=1.27`, the first Hatchling
version identified by the Python Packaging User Guide as supporting PEP 639
license metadata.

Project metadata should be static unless a field has a documented reason to
be dynamic. The version is the sole initial dynamic field.

### Source layout

Importable code will live under `src/importtime_check/`. Tests must exercise
an installed package or built wheel rather than make the repository root
importable. This prevents a checkout from masking missing or incorrectly
packaged files.

### Version source

The only version literal will be a PEP 440 version assigned to `__version__`
in `src/importtime_check/_version.py`. Hatchling will read that file through
its regular-expression version source, and `importtime_check.__init__` will
re-export the same value.

The first release version is `0.1.0a1`. Releases use Semantic Versioning for
intent and PEP 440 syntax for package metadata. Importing the version must not
query installed metadata, invoke Git, access the network, or import the build
backend.

### Python compatibility

Package metadata will declare `requires-python = ">=3.11"` with no upper
bound. The initial documented and continuously tested support matrix is Python
3.11 through 3.14.

Python 3.15 will be added to classifiers and the claimed test matrix after a
stable interpreter and the project's build, test, and lint toolchain complete
a verified lane. The open-ended metadata allows users to test newer Python
versions without an artificial resolver failure, but documentation must not
claim compatibility until CI enforces it.

Dropping a tested Python version or adding an exclusion requires a design
issue, evidence, migration notes, and a release that communicates the change.
Supporting an interpreter means its core unit, packaging, and artifact smoke
tests run continuously; an untested classifier is not permitted.

### Dependency boundaries

The core runtime dependency list is empty. Measurement, parsing, comparison,
configuration, and terminal or JSON reporting use the Python standard library.

Pytest support and future framework, database, cloud, or engine integrations
remain optional. `import importtime_check` and all core APIs must succeed when
none of those integrations are installed. Development-only tools must not be
declared as runtime dependencies.

Adding a required runtime dependency or changing the optional-integration
boundary requires a design issue covering import cost, license, security,
maintenance, and failure behavior.

### License and typed-package data

Metadata will use the SPDX expression `Apache-2.0` and explicitly include
`LICENSE` and `NOTICE` as license files in wheels and source distributions.
Legacy license classifiers or the deprecated license table form will not be
used.

The package will include `py.typed` when its first typed public API is shipped.
The marker must be present in both the wheel and source distribution.

## Ownership boundaries

- `pyproject.toml` owns build-system selection and published project metadata.
- `src/importtime_check/_version.py` owns the version literal.
- `src/importtime_check/__init__.py` may re-export the version but must not
  define another version literal or perform metadata lookup.
- Hatchling translates the source tree and metadata into wheel and source
  distribution artifacts; it is not a runtime dependency.
- Core modules own no optional-integration imports at module import time.
- CI owns the evidence for every claimed Python version and artifact contract.

## Validation and failure semantics

Packaging implementation and every release must validate all of the following:

1. Build one wheel and one source distribution through the PEP 517 frontend.
2. Run Twine metadata validation on both artifacts.
3. Inspect artifact contents for the package, version module, `LICENSE`,
   `NOTICE`, and `py.typed` once typing is public.
4. Install the built wheel into a clean temporary environment without editable
   mode.
5. Import `importtime_check` with no optional integrations installed and
   verify `importtime_check.__version__` exactly matches artifact metadata.
6. Run the supported-Python test matrix against installed artifacts.

The build must fail if Hatchling cannot parse the version, required metadata
is invalid, or a declared license file is absent. Artifact validation must fail
if wheel and source distribution versions differ, required files are missing,
or a clean core import needs an optional dependency. Publication must not
proceed after any such failure.

## Compatibility policy

Before `1.0.0`, minor releases may deliberately change the public API, but the
changelog and release notes must identify those changes. Patch releases must
remain compatible within their minor line. Reaching `1.0.0` requires a
separate stability review.

The version file format, distribution name, import name, Python floor, core
dependency boundary, and serialized configuration or baseline formats are
compatibility contracts. Changes to them require an issue and, when material,
a superseding design record.

## Alternatives considered

### Setuptools

Setuptools is mature and broadly compatible. It was not selected because this
pure-Python package does not need its wider extension and legacy configuration
surface. It remains a viable fallback if Hatchling cannot meet a demonstrated
packaging need.

### Flit Core

Flit Core offers a small standards-focused backend. Hatchling was selected
because its documented file-based version source fits the explicit
`_version.py` contract and leaves room for later artifact customization without
introducing a version plugin.

### Flat source layout

A top-level `importtime_check/` directory would be simpler to execute directly
from a checkout. It was rejected because the checkout would be placed on the
import path and could conceal packaging errors that appear only in installed
artifacts.

### Static version in `pyproject.toml`

A static project version is simple for build tools, but exposing a runtime
`__version__` would then require duplication, generated code, or an installed
metadata lookup. The small `_version.py` source avoids all three and keeps
package import deterministic.

### Git-derived versions

Deriving versions from tags was rejected because builds from source
distributions must not require a Git checkout, and releases must build the
reviewed version explicitly rather than infer it from ambient repository state.

### Supporting Python 3.10 or earlier

This would expand initial reach, but those interpreters are already end of life
upstream. The added compatibility and security burden is not justified for a
new, unreleased tool. Requiring Python 3.12 or newer was also rejected because
the current design needs no feature that justifies excluding supported Python
3.11 users.

## Consequences

- Contributors need an installation step to run the package from a checkout.
- Packaging errors become visible earlier because tests cannot accidentally
  import a top-level source directory.
- Build isolation downloads Hatchling even though end users receive a
  dependency-free runtime package.
- The direct version import stays small and suitable for a tool focused on
  import performance.
- Optional integrations require explicit extras and isolated test lanes.
- Supporting Python 3.11 increases the matrix until its upstream lifecycle and
  a reviewed compatibility change permit removal.

## Implementation follow-ups

Separate issues will:

1. add the minimal `pyproject.toml`, source package, version export, and
   `py.typed` marker;
2. test metadata, version consistency, core import isolation, and artifact
   contents;
3. add formatting, linting, typing, testing, and coverage policy;
4. add supported-Python and artifact CI lanes; and
5. add release validation and Trusted Publishing after the package behavior is
   ready for an alpha release.

## Primary references

- [Writing `pyproject.toml`](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
- [`src` layout vs flat layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)
- [Hatch version source configuration](https://hatch.pypa.io/dev/version/)
- [Python version status](https://devguide.python.org/versions/)
- [PEP 440 version identification](https://packaging.python.org/en/latest/specifications/version-specifiers/)
- [PEP 639 license metadata guidance](https://packaging.python.org/en/latest/guides/licensing-examples-and-user-scenarios/)
