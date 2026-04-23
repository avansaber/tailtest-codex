# Changelog

## [4.5.0] -- 2026-04-23

C# / .NET language support. 348 tests.

**Detection:** New `detect_dotnet_runner` picks up projects with `*.csproj`, `*.sln`, or `global.json`. Runner is `dotnet test`. Enumerates test projects into `runners.csharp.test_projects` for per-source-file resolution at test-write time.

**R1 baseline:** `null`, `default(T)`, empty `IEnumerable<T>`, `ArgumentNullException`, zero / negative numeric.

**Scenario rules:** xUnit, NUnit, MSTest patterns; Moq for mocking; avoid mocking DbContext (use in-memory provider); `WebApplicationFactory<Program>` for ASP.NET Core integration; determinism guidance.

**Monorepo detection:** `*.sln` at project root now marks a project as monorepo-like.

## [4.4.0] -- 2026-04-23

Kotlin language support. 340 tests.

**Kotlin baseline scenarios (R1):** Kotlin row added: `null`, empty collection, zero, negative, `Result.failure`.

**Kotlin test path resolution:** Tests target `src/test/kotlin/{Name}Test.kt`. Java runner picks `src/test/kotlin/` when only the Kotlin test directory exists; mixed Java+Kotlin projects default to `src/test/java/` with per-source-file path overrides.

**Kotlin Scenario rules:** Covers `kotlin.test` assertions, JUnit 5 lifecycle, `runTest { }` for coroutines, `sealed class` exhaustiveness, `data class` equality, `Result<T>` testing.

## [4.3.0] -- 2026-04-23

NestJS and Flask framework support. 337 tests.

**NestJS detection:** Projects with `@nestjs/core` in dependencies register as `framework: nestjs`. NestJS is checked before Next.js (more specific signal). Monorepos with different frameworks per package are detected correctly. R2 row + S-rules entry covers Test.createTestingModule, provider overrides, controller vs microservice variants.

**Flask detection:** Projects with `flask` in pyproject deps register as `framework: flask`. For the rare both-declared case, entry-point file inspection picks the right one. Falls back to fastapi for ambiguous cases (preserves pre-V12.2 behavior). R2 row + S-rules entry covers test_client, app context, blueprints, pytest-flask.

**S-rules additions:** New NestJS and Flask entries in the Scenario rules section.

## [4.2.0] -- 2026-04-23

Spring Boot R2 baseline + Bun test, Deno test, pytest-asyncio detection. 329 tests.

**Spring Boot (R2 completion):** Spring Boot projects (Maven or Gradle with `spring-boot` referenced) now get auto-included baseline scenarios on top of the Java baseline: valid request returns 200, missing required field returns 400, unauthenticated request returns 401, controller slice test with `@WebMvcTest`, service dependency overridden via `@MockBean`. Detection and Scenario rules already shipped in v4.1.0; this completes the R2 framework template row.

**Bun test detection:** Projects with `bun test` in `package.json` `scripts.test` or with `bunfig.toml` present now get the `bun test` runner instead of falling back to `vitest`. Precedence is explicit: scripts > deps > `bunfig.toml` tiebreaker.

**Deno test detection:** New `detect_deno_runner` function picks up Deno projects via `deno.json` or `deno.jsonc`. Tests are colocated (`*_test.ts` style) with `deno test` as the runner. When both `package.json` and `deno.json` exist, Node wins.

**pytest-asyncio:** Detected via `pytest-asyncio` in pyproject deps. Adds an additive `async_framework` field on the python runner entry. No schema break.

**Mock the right library (S-rules update):** Expanded to cover Bun and Deno mocking syntax with warning against mixing runners.

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
