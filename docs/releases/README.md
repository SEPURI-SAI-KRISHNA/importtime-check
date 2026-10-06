# Release process

Issue [#28](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/28)
tracks the first public alpha through publication and post-release
verification. Preparation changes use a separate issue and pull request so
merging the preparation PR does not close #28 prematurely. The release issue
and milestone close only after exact verification results are recorded.

## Before creating the tag

1. Merge the release-preparation PR only after aggregate CI passes. Review its
   CodeQL, dependency-review, DCO, test-matrix, build, Twine, artifact, and
   clean-wheel jobs. Confirm the package version is still `0.1.0a1` and
   [release notes](v0.1.0a1.md) are reviewed.
2. Resolve the old dependency PR #13 without merging its unlinked historical
   body: the preparation PR includes its pinned `actions/upload-artifact`
   update. Close #13 as superseded after that change is merged; do not edit
   its historical description. Confirm no other required milestone issue is
   open. #28 itself stays open until post-release verification.
3. Create a GitHub tag ruleset protecting `v*` from unauthorized creation,
   update, and deletion. Create a `pypi` GitHub environment with required
   approval and deployment restricted to `main`. These repository settings
   are not created by a pull request and must be checked in Settings.
4. On PyPI, register a pending Trusted Publisher for project
   `importtime-check`, owner `SEPURI-SAI-KRISHNA`, repository
   `importtime-check`, workflow `release.yml`, and environment `pypi`.
   A pending publisher does **not** reserve the package name; verify that the
   name is still available immediately before release. Do not create a PyPI
   API token for this workflow.
5. Verify the latest `main` CI run is successful. Set the repository Actions
   variable `PYPI_RELEASE_APPROVED` to `0.1.0a1` only after deliberately
   approving this exact release. Review workflow permissions and the
   environment protection before setting it.

## Publish only after deliberate approval

Create the protected `v0.1.0a1` tag at the current `main` commit using your
normal Git workflow. From the Actions tab, run `Release to PyPI` on `main`
with tag `v0.1.0a1` and confirmation `publish 0.1.0a1`. Do not use a local
workstation or stored token to upload distributions.

The workflow fails closed unless the tag, version, manual confirmation,
approval variable, dispatched `main` commit, latest CI result, milestone, and
PR #13 state agree. It builds one wheel and one sdist from the verified commit,
checks both with Twine, inspects the artifacts, smoke-installs the exact wheel,
generates build provenance, and preserves those bytes as one Actions artifact.
After the protected `pypi` environment is approved, a separate minimal OIDC
job retrieves and publishes that artifact. PyPI's official publishing action
adds publish attestations by default. A final job attaches the same files and
the reviewed notes to a GitHub prerelease. Any failure stops the dependent
jobs; do not retry with different files under the same version.

## Verify and close

In Issue #28, record the exact workflow run, tag and commit, wheel and sdist
SHA-256 hashes, PyPI file URLs and metadata, trusted-publisher provenance,
GitHub release URL, and clean-install checks. Install from PyPI in fresh
CPython 3.11 and 3.14 environments and verify the version, parser, CLI
measure/record/check path, zero core dependencies, and the optional pytest
extra. Confirm docs and default-branch CI remain healthy. Remove the
`PYPI_RELEASE_APPROVED` variable after successful publication. Only then
close #28 and the `0.1.0a1` milestone.

If PyPI or GitHub disagrees with the reviewed artifacts, stop. PyPI files
cannot be replaced in place. Document the defect, yank only if justified,
open an issue, and prepare a new version; never delete or overwrite a
published file to conceal a problem.

References: [PyPI pending publishers](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/),
[PyPI publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/),
[PyPI attestations](https://docs.pypi.org/attestations/producing-attestations/),
and [GitHub environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).
