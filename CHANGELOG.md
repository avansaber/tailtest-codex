# Changelog

## [4.1.0] -- 2026-04-20

Quality layer and cross-session memory. 317 tests.

**Rule layer:** Fourteen rules now govern test generation -- requirement-first derivation, language-keyed baseline scenarios, flakiness ban list, AAA structure, one-behavior-per-test, plain-English names, no-internals rule, boundary-only mocking, framework templates (Django, FastAPI, Next.js), equivalence partitioning, pre-write API check, SCENARIO PLAN label, and failure classification (real bug / environment issue / test bug stated before asking to fix).

**Hook enrichment:** Per-file depth scoring (path signals: auth/billing +4, admin/delete +3; content signals: HTTP/DB +3 each; up to 15 scenarios for critical files). Cross-turn context: prior session failures injected at session start. Long test output compressed to function name, assertion, expected/received.

**Cross-session memory:** `.tailtest/history.json` tracks outcomes across sessions (1000-entry cap, gap/passed/fixed/regression classification). Recurring failures (3+ sessions) flagged at startup.

**Opt-in:** Impact tracing (Python AST, `impact_tracing: true`), API validation (`api_validation: true`).

## [Unreleased]

## [4.0.0] -- 2026-04-18

Initial Codex CLI port. SessionStart hook for project orientation and AGENTS.md injection.
Stop hook with mtime-based file detection per agent turn. All 8 languages (Python,
TypeScript, JavaScript, Go, Rust, Ruby, PHP, Java). Codex skill files. 288 tests.
