# 0025 — Tests State The Business Risk

Every automated test must name the business failure it catches.

## Problem

Low-value tests create drag: they lock implementation details, inflate change cost,
and make engineers maintain assertions that do not protect users, money, data, or
operations. This became visible when config-cleanup tests only proved that a
mocked task branch read a new setting name.

## Decision

Every test must include a docstring or nearby comment that states the business
case it protects. If that business case cannot be articulated, delete the test
instead of updating it.

This applies to every test added or touched in a change. A class-level docstring
is sufficient when all tests in that class protect the same business risk;
otherwise the individual test needs its own nearby comment.

## Why

Tests are only valuable when they prevent a meaningful regression. Requiring the
business risk in the test keeps coverage tied to observable system value: data
integrity, customer workflows, accounting correctness, operational safety, or
security. It also makes reviews faster because the reader can judge the test's
worth without reverse-engineering intent from mocks.

## Alternatives considered

- **Coverage-count target:** easy to measure, but rewards shallow tests and makes
  deletion politically harder even when the tests are noise.
- **Reviewer judgment only:** flexible, but intent disappears after the review
  and the next maintainer cannot tell whether a test protects behavior or just
  an old implementation detail.

## Consequences

Tests may be deleted during refactors when no business risk is clear. New tests
carry a small writing cost, but the suite should be smaller, clearer, and more
defensible.
