# 0004: Contributor-friendly templates

- Status: Accepted when the pull request containing this record merges
- Decision date: 2026-10-03
- Decision issue: [#14](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/14)
- Supersedes: [0003](0003-contribution-governance-and-release-tracking.md) for template enforcement
- Owners: `importtime-check` maintainers

## Context

The first contribution-policy implementation treated issue and pull request
bodies as machine schemas. It required exact headings, closed issues
automatically, and blocked pull requests when prose did not match a custom
validator. That was stricter and less welcoming than the intended
Apache-inspired workflow.

Templates should help contributors explain work and help reviewers find the
important evidence. They should not turn ordinary collaboration into a form
compliance exercise. Existing merged issue and pull request descriptions also
remain historical records and must not be rewritten merely for visual
uniformity.

## Decision

### Issue templates

Blank issues remain disabled. Five concise forms cover Bug reports, Feature
proposals, Design proposals, Maintenance tasks, and Release checklists. Each
form requires only the information essential to that contribution type and
leaves secondary context optional.

Maintainers review submissions normally and ask for missing information when
needed. No workflow parses issue prose or automatically closes an issue for
using different wording.

### Pull request template

Every project-authored pull request uses these sections in this order:

1. What changes are proposed?
2. Why are these changes needed?
3. Related issue.
4. User-facing behavior or migration impact.
5. Validation.
6. Compatibility, risk, and rollback.
7. Documentation and follow-up.
8. Checklist.

The checklist covers issue linkage, tests, documentation, compatibility,
private data, and DCO sign-off. It contains no checkbox asking an author to
confirm that they preserved the template itself.

GitHub pre-fills the tracked template. Maintainers request corrections during
review instead of using a custom body validator. Branch protection continues
to require a pull request and aggregate CI.

### Release notes

The user-facing impact section records behavior and migration information.
Maintainers use release-category labels for user-visible work and
`skip-release-notes` for internal-only changes. A separate mandatory changelog
edit is not required for every pull request.

### Historical records

Merged and closed issue or pull request descriptions are not edited to imitate
new templates. Template evolution is prospective and documented through this
record. Unmerged work may be replaced with a correctly formatted pull request
after its prerequisites are satisfied.

## Ownership boundaries

- Issue Forms provide focused prompts.
- The pull request template provides a consistent review narrative.
- Maintainers own triage and template review.
- CI owns executable quality and artifact evidence.
- Repository rules own pull-request and CI enforcement.
- Milestones and labels own release tracking and classification.

## Validation and failure semantics

Repository validation checks that Issue Form YAML is valid, blank issues are
disabled, the pull request template contains the eight approved sections, and
CI remains required. It does not parse contributor-authored issue or pull
request prose.

## Alternatives considered

Exact body validation was rejected because it makes harmless wording changes
fail and creates a poor contributor experience. Advisory templates with no
review expectations were also rejected because they do not provide a stable
project workflow. Concise templates plus maintainer review provide consistent
records without unnecessary automation.

## Consequences

- Contributors receive shorter, more relevant prompts.
- Maintainers use judgment for incomplete submissions.
- GitHub API clients can bypass templates, so review remains necessary.
- Historical descriptions remain accurate records of their time.
- Future template changes require an explicit governance decision.

## Primary references

- [Apache Spark pull request template](https://github.com/apache/spark/blob/master/.github/PULL_REQUEST_TEMPLATE)
- [Apache Airflow pull request template](https://github.com/apache/airflow/blob/main/.github/PULL_REQUEST_TEMPLATE.md)
- [Apache Fesod pull request template](https://github.com/apache/fesod/blob/main/.github/pull_request_template.md)
- [GitHub pull request templates](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/creating-a-pull-request-template-for-your-repository)
