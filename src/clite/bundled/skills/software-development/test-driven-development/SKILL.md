---
name: test-driven-development
description: Implement a feature or fix by writing a failing test first. Use when adding behaviour to tested code or when a bug needs a regression test.
version: 1.0.0
author: C-lite
license: MIT
metadata:
  clite:
    tags: [testing, engineering]
    category: software-development
    requires_toolsets: [terminal]
---

# Test-driven development

## Steps

1. **Write one test** for the next small piece of behaviour. Name it for the behaviour:
   `test_expired_token_is_rejected`, not `test_auth_2`.
2. **Run it and watch it fail** for the reason you expect. A test that passes before the
   code exists is testing nothing.
3. **Write the least code** that makes it pass.
4. **Run the test, then the nearby tests.**
5. **Refactor** with the tests green. Run them again.
6. Repeat. Commit at each green state.

## What makes a test worth keeping

- It asserts behaviour a caller depends on, not how the code is arranged inside.
- It fails when the behaviour breaks and for no other reason. A test that breaks on every
  refactor gets deleted, and then it protects nothing.
- It runs without the network, without real credentials, and against a temporary directory.

## Pitfalls

- Asserting on a snapshot of data that is expected to change (a model list, a version).
  Assert the relationship instead.
- Mocking the thing under test. Mock the boundary (the network, the clock), run the rest.
- Reading the source file in a test and matching its text. That tests the spelling, not the
  behaviour.
