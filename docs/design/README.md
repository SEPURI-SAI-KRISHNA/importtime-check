# Design records

This directory contains decisions that define long-lived contracts for
`importtime-check`. A design record is required before changing public APIs,
serialized formats, compatibility promises, architecture, dependency policy,
security-sensitive behavior, or release policy.

## Format

Design records use four-digit sequential numbers and descriptive names, for
example `0001-packaging-and-compatibility.md`. Each record documents:

- context and the user or maintainer problem;
- the decision and its ownership boundaries;
- validation and failure semantics;
- compatibility and migration expectations;
- alternatives considered;
- consequences and implementation follow-ups; and
- links to the deciding issue and primary sources.

## Records

1. [0001: Packaging and compatibility contract](0001-packaging-and-compatibility.md)
2. [0002: Quality and test policy](0002-quality-and-test-policy.md)

## Lifecycle

- **Proposed:** discussion is active and implementation must not depend on the
  decision yet.
- **Accepted:** the pull request containing the record was merged. Merging is
  the acceptance action; a separate vote or administrative action is not
  implied.
- **Superseded:** a later accepted record replaces all or part of the decision.
  Both records remain available, with links in each direction.

A record added with `Status: Accepted` describes the state that takes effect
only when its pull request is merged. Rejecting or closing the pull request
leaves no accepted decision. Material changes to an accepted record require a
new design issue and normally a superseding record rather than silently
rewriting history.
