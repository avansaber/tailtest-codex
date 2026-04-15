---
name: tailtest
description: Run tailtest on a specific file -- generate test scenarios, write the test file, execute, and report failures.
---

Generate or update tests for $ARGUMENTS.

Read the source file at `$ARGUMENTS`. Generate production-like test scenarios covering its public surface -- happy path, key edge cases, and failure modes at the configured depth. Write or update the test file following the tailtest Step 4 rules in AGENTS.md (correct location, correct name, style-matched to existing tests). Run the tests and report only failures; stay silent if all pass.

Treat the file as new-file regardless of its git status -- this skill explicitly requests generation even for legacy files or files the Stop hook would normally skip.

After completing, update `.tailtest/session.json`: add the file to `generated_tests` and clear it from `pending_files` if present.
