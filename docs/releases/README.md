# Release process

Use this runbook for each deliberately approved release. `VERSION` means the
literal value in `src/importtime_check/_version.py`; `TAG` means `vVERSION`.
For example, version `0.1.0a2` uses tag `v0.1.0a2`, milestone `0.1.0a2`,
release issue title `release: 0.1.0a2`, and reviewed notes in
`docs/releases/v0.1.0a2.md`. The release-preparation changes use a separate
issue and PR, so merging them does not close the release issue prematurely.

## Before creating the tag

1. Merge the release-preparation PR only after aggregate CI passes. Review its
   CodeQL, dependency-review, DCO, supported-Python test matrix, build, Twine,
   artifact, and clean-wheel results. Confirm the source version, package
   metadata, documentation, and `docs/releases/TAG.md` agree.
2. Confirm exactly one **open** milestone is titled `VERSION`, with exactly
   one **open** issue titled `release: VERSION` in it. Every other issue in
   that milestone must be closed. Keep the release issue and milestone open
   through publication and post-release verification. Resolve dependency or
   other open PRs as part of normal preparation; no historical PR number is a
   standing release exception.
3. Confirm GitHub tag rules protect `v*` from unauthorized creation, update,
   and deletion. Confirm the `pypi` environment still requires reviewers and
   restricts deployments to protected `main`. These repository settings are
   not created by a PR; inspect them in Settings for each release.
4. Confirm PyPI Trusted Publishing names this repository, `release.yml`, and
   environment `pypi`. Do not create a PyPI API token for this workflow.
   For a first publication, a pending publisher does not reserve a package
   name; verify availability immediately before publishing.
5. Verify the latest `main` CI run for the candidate commit is green. Only
   after deliberately approving this exact release, set the repository
   Actions variable `PYPI_RELEASE_APPROVED` to `VERSION`. Do not set it to a
   future version or leave a previous approval in place.

## Publish only after deliberate approval

Create protected tag `TAG` at the current `main` commit using your normal Git
workflow. From Actions, dispatch **Release to PyPI** on `main` with tag `TAG`
and confirmation `publish VERSION`. Do not use a workstation or stored token
to upload distributions.

The read-only preflight fails closed unless source version, tag, confirmation,
approval variable, dispatched `main` commit, latest successful CI, the one
matching open milestone and release issue, closure of all other milestone
issues, and the protected `pypi` environment agree. It does not authorize a
release merely because an old milestone or unrelated issue is open.

The workflow then builds one wheel and one sdist from the verified commit,
checks both with Twine, validates exact artifacts, smoke-installs the wheel,
generates build provenance, and preserves those bytes as one Actions artifact.
After the protected `pypi` environment is approved, a separate minimal OIDC
job retrieves and publishes that same artifact. PyPI's official publishing
action adds publish attestations by default. A final job attaches the same
files and the reviewed `docs/releases/TAG.md` notes to a GitHub prerelease.
Any failure stops dependent jobs; never retry with different files under the
same version.

## Verify and close

In the open `release: VERSION` issue, record the exact workflow run, tag and
commit, wheel and sdist SHA-256 hashes, PyPI file URLs and metadata,
trusted-publisher provenance, GitHub release URL, and clean-install results.
Check the published functionality in fresh environments for the supported
Python range, including the optional pytest extra when relevant. Confirm
documentation and default-branch CI remain healthy. Remove the one-time
`PYPI_RELEASE_APPROVED` variable after successful publication. Only then
close the release issue and milestone.

If PyPI or GitHub disagrees with the reviewed artifacts, stop. Published PyPI
files cannot be replaced in place. Document the defect, yank only if justified,
open an issue, and prepare a new version; never delete or overwrite a file to
conceal a problem.

References: [PyPI pending publishers](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/),
[PyPI publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/),
[PyPI attestations](https://docs.pypi.org/attestations/producing-attestations/),
and [GitHub environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).
