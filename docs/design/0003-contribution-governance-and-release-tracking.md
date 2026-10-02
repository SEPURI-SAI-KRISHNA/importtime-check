# 0003: Contribution governance and release tracking

- Status: Accepted
- Acceptance: merge of the pull request that adds this record
- Decision date: 2026-10-02
- Decision issue: [#14](https://github.com/SEPURI-SAI-KRISHNA/importtime-check/issues/14)
- Owners: `importtime-check` maintainers

## Context

Issue Forms and pull request templates improve submissions, but by themselves
they are advisory. Maintainers can still choose a blank issue, API and CLI
clients can supply any body, and an author can delete a pre-filled pull request
template. A repository that promises issue-first development needs a machine
check and protected-branch rule behind that promise.

The project also needs release tracking before product implementation begins.
Milestones, labels, changelogs, and project boards overlap unless each has a
clear owner. Requiring every pull request to edit one changelog would turn CI,
test, dependency, and refactoring work into user-facing noise. Omitting release
classification entirely would instead defer all curation until release day.

## Decision

### Issue-first development

Every pull request must close one open issue in this repository. The linked
issue must use an approved form and have a milestone before the pull request
can pass policy validation. A pull request cannot substitute for its planning
issue, even for maintainer or automated dependency work.

The approved forms are Bug report, Feature request, and Implementation task.
They own the required structure for defects, proposals, and already-approved
work respectively. Their `bug:`, `feature:`, and `task:` title prefixes identify
the selected contract. Blank public issues remain disabled.

An issue workflow validates new, edited, and reopened bodies. A submission that
does not match an approved rendered form is explained and closed. GitHub cannot
prevent every API-created issue before creation, so prompt closure is the
enforcement boundary for bypasses.

### Pull request contract

Every pull request retains the tracked sections for summary, closing issue,
validation, compatibility and risk, documentation, release note, and checklist.
The closing reference is a same-repository `Closes #NUMBER`, `Fixes #NUMBER`,
or `Resolves #NUMBER` statement. The referenced item must be an open issue, not
another pull request.

Pull request titles use an approved Conventional-Commit-style type, optional
lowercase scope, imperative summary, and an 80-character maximum. The accepted
types are `build`, `chore`, `ci`, `docs`, `feat`, `fix`, `perf`, `refactor`, and
`test`. Squash-merged history can therefore support useful release grouping
without placing issue identifiers in titles.

The policy workflow uses `pull_request_target` only as a trusted metadata
boundary. It checks out `main`, executes the validator from `main`, grants read
permissions, and never checks out or executes contributor-controlled code.
Ordinary CI continues to use `pull_request` and tests the proposed source.

### Release tracking

Milestones own version-level progress. Issues, rather than both issues and
their pull requests, receive the release milestone so one unit of work is not
double-counted. The first milestone is `0.1.0a1`; later release-bound work uses
the corresponding version milestone. Labels own change classification.

GitHub Projects are deferred while work is primarily sequential. A project may
later own workflow state, priority, and roadmap views, but it must not replace
the milestone as the release scope or the issue as the work contract.

### Release notes and changelog

Every pull request chooses exactly one documentation outcome and one release
note outcome, with concrete text. User-visible behavior, compatibility, and
documented usage receive a release-note summary. CI, tests, refactoring, and
other internal maintenance normally explain why no note is needed. A
user-visible change carries a generated-release-note category label; a
non-user-visible change carries `skip-release-notes`. Policy validation keeps
the selected outcome and labels consistent.

GitHub generated release notes group merged pull requests by labels for the
initial alpha. CI does not require every pull request to modify a monolithic
`CHANGELOG.md`. A curated changelog or Towncrier-style fragments require a
later issue when release frequency, maintenance branches, or contributor
concurrency demonstrates the need.

### Merge enforcement

The `main` ruleset requires a pull request, blocks branch deletion and force
pushes, and requires the aggregate `CI` and `Pull request policy` checks. An
approval count is not required while the repository has one maintainer because
self-approval would not provide independent review evidence.

## Ownership boundaries

- Issue Forms own required planning inputs; issues own one focused unit of work.
- The pull request template owns review evidence and the closing issue link.
- Contribution-policy workflows own mechanical template and linkage checks.
- Ordinary CI owns source, test, compatibility, and artifact evidence.
- Milestones own release scope and progress; labels own classification.
- Generated release-note configuration owns initial release grouping.
- Repository rules own merge enforcement and direct-push prevention.

## Validation and failure semantics

Issue validation fails when headings differ from every approved form, a
required response is empty, a confirmation is unchecked, the title prefix is
wrong, or the obsolete `Planning metadata` footer appears.

Pull request validation fails when the title or body contract changes, required
text is absent, documentation or release-note choices are ambiguous, checklist
confirmations are incomplete, or the closing reference does not resolve to an
open, form-compliant, milestone-assigned issue. GitHub API failures fail closed;
they do not silently waive issue verification.

The validator is standard-library Python with deterministic unit tests. The
issue workflow may write only issue comments and state. The pull request policy
has read-only permissions. All third-party actions use complete commit hashes.

## Alternatives considered

### Advisory templates only

This is GitHub's default and has little maintenance cost, but it cannot uphold
a mandatory policy because every template can be bypassed or deleted.

### Pull requests without issues for small changes

This reduces one step for trivial work, but creates an ambiguous exception and
makes release scope incomplete. Small issues may remain concise; they are still
required.

### Review approval requirement

Independent review is valuable, but a single maintainer cannot approve their
own pull request meaningfully. The ruleset can add a positive approval count
when another regular maintainer is available.

### Changelog updates in every pull request

This is simple to check but confuses developer history with user-facing news
and creates unnecessary conflicts. Selective release-note classification keeps
the decision visible without forcing noise into a shared file.

### Immediate news fragments

Towncrier-style fragments scale well and are used by mature Python projects.
They add configuration, a development dependency, fragment taxonomy, and a
release compilation process before this project has a first behavior or a
maintenance branch. The design leaves that migration open when scale warrants
it.

## Consequences

- Contributors receive explicit forms and fast feedback instead of discovering
  missing review context late.
- Automated pull requests require a linked issue before merge.
- Maintainers must assign a milestone before implementation reaches review.
- Metadata validation is separate from untrusted code execution.
- Release progress and generated notes are useful without duplicate milestone
  accounting or mandatory changelog noise.
- Repository settings need a post-merge ruleset step because Git cannot store
  GitHub enforcement settings.

## Primary references

- [GitHub issue and pull request templates](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/about-issue-and-pull-request-templates)
- [GitHub Issue Form syntax](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-issue-forms)
- [GitHub pull request issue linking](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/linking-a-pull-request-to-an-issue)
- [GitHub milestones](https://docs.github.com/en/issues/using-labels-and-milestones-to-track-work/about-milestones)
- [GitHub repository rules](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)
- [GitHub generated release notes](https://docs.github.com/en/repositories/releasing-projects-on-github/automatically-generated-release-notes)
- [Apache Airflow pull request template](https://github.com/apache/airflow/blob/main/.github/PULL_REQUEST_TEMPLATE.md)
- [pytest contribution guide](https://github.com/pytest-dev/pytest/blob/main/CONTRIBUTING.rst)
- [Towncrier documentation](https://towncrier.readthedocs.io/en/stable/)
