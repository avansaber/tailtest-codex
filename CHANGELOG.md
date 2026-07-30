# Changelog

## [Unreleased]

Codex hook contract and packaging repair.

- Plugin hook commands now resolve bundled scripts through `PLUGIN_ROOT`, with `commandWindows` overrides.
- `SessionStart` covers startup, resume, and compact; resume preserves pending state and plugin instructions are returned as context without writing a project `AGENTS.md`.
- `PostToolUse` recognizes canonical `Bash` and `tool_input.command`, emits `hookEventName: "PostToolUse"`, and rejects paths outside the active project.
- `Stop` blocks whenever pending work remains, even when the end-of-turn sweep finds no newly changed files.
- Project-local session state is now type-checked and bounded before automatic hooks consume it; restored pending paths must resolve beneath the real project root.
- SessionStart, PostToolUse, and Stop now place repository-derived file values in explicitly labeled, bounded JSON data instead of mixing them directly into plugin instructions.
- SessionStart now injects compact trusted runtime instructions and caps the complete UTF-8 context payload at 8 KiB; legacy `AGENTS.md` fallback content is bounded explicitly.
- Stop now honors `/tailtest defer` and explicit no-further-tools user directives after persisting the validated queue, while fenced, quoted, and indented examples remain inert data and default turns continue to block on pending work.
- Hook launchers leave the untrusted project directory before resolving Python while preserving the original project root for hook state, and automatic Git probes resolve an absolute executable outside the project tree.
- The direct-clone initializer materializes absolute project-hook commands instead of leaking plugin-only environment variables into project scope.
- Added behavior-level regression coverage for manifest matching, Windows commands, installer output, canonical event payloads, resume state, output schema, queue persistence, and path containment.
- Validation passes on Windows (458 tests) and WSL/Linux (452 passed, 6 platform skips); Ruff lint and format checks are clean on both.

## [4.9.1] -- 2026-05-26

Plugin icon for the Codex marketplace display.

- Added `assets/icon.svg` (512x512, rounded-square tile with the tailtest shield + checkmark mark, emerald on near-black). Reads cleanly at marketplace tile sizes (32px, 64px, 128px).
- `.codex-plugin/plugin.json` now references the icon via `interface.composerIcon = "./assets/icon.svg"`. Per the Codex plugin manifest spec; renders in the Codex app composer / marketplace browser.
- No behavioral changes. 400 tests still passing.

Triggered by `tailtest-codex#5` (thanks to `@internet-dot` for the report and the concrete instructions).

## [4.9.0] -- 2026-05-19

PostToolUse migration. Per-edit feedback alongside the existing turn-end Stop sweep. 400 tests (was 380; +20 PostToolUse tests).

**New `hooks/post_tool_use.py`:**
- Fires after every file-mutating Codex tool call (`apply_patch`, `patch`, plus shell-style tools via mtime fallback).
- For `apply_patch` payloads, parses two envelope forms: standard unified diff (`diff --git a/path b/path`) and Codex's `*** Update File: path` / `*** Add File: path` form.
- For shell tools or unparseable patches, falls back to an mtime sweep since the last PostToolUse fire. This catches files written via redirection, build steps, etc.
- Applies the same intelligence filter as the Stop hook (`is_filtered`, `detect_language`, runner-required gating).
- Loop guard: files that appear in `generated_tests` values are skipped, preventing infinite test loops when the agent writes a test file.
- Honors the existing pause state and silently exits on inactive sessions.
- Output uses the `{"hookSpecificOutput": {"additionalContext": "..."}}` envelope so the agent sees newly queued files mid-turn without the hook blocking the turn.

**Stop hook unchanged in behavior:** still sweeps mtimes at end of turn as a safety net, picking up anything PostToolUse missed. The mtime walker now lives in `hooks/lib/scanner.py` so both hooks share the same implementation; `stop.py` keeps a thin back-compat wrapper named `sweep_changed_files` so existing tests still pass.

**`hooks/hooks.json` updated:** now registers SessionStart + PostToolUse + Stop. The PostToolUse entry uses `matcher: ".*"` to fire on every tool. SessionStart matcher set to `"startup"` to match the documented Codex hooks spec.

**User-visible UX change:** Codex no longer waits until the turn boundary to surface queued files. As soon as `apply_patch` writes a file, the agent receives an `additionalContext` note listing it. Per-edit responsiveness matches the Claude Code variant.

**Note on Codex `codex exec` mode:** hooks fire only in interactive `codex` sessions; `codex exec` (non-interactive batch mode) does not load hook configuration as of Codex CLI 0.130.0. This is an upstream Codex limitation, not a tailtest issue. Manual validation in real interactive sessions remains the canonical smoke test.

## [4.8.0] -- 2026-05-19

Codex CLI parity refresh against Codex 0.129.0+. Docs + plugin manifest + marketplace structure. No detection / rule / hook code changes; 380 tests still passing.

**Docs cleanup (Phase A):**
- README and `tailtest.com/docs/codex` install sections no longer instruct users to set `[features].codex_hooks = true`. Hooks reached GA in Codex 0.129.0 (default-on); the legacy alias still works but emits a deprecation warning every session. Older-version subsection added that documents the post-deprecation `[features].hooks = true` flag for users pinned to pre-0.129.0 releases.
- `scripts/init.sh` feature-flag check rewritten. Silent on current Codex defaults; emits a clean deprecation notice only when the user's `~/.codex/config.toml` still has the legacy `codex_hooks` key. Header comment updated to reference the new key.

**Plugin manifest + marketplace structure (Phase B):**
- `.codex-plugin/plugin.json` updated to current Codex spec form: `hooks` and `skills` as string paths instead of object/array forms. Version bumped to 4.8.0. Added `interface` block (displayName, descriptions, capabilities, defaultPrompt, brandColor) so the plugin renders properly in Codex's `/plugins` browser and any marketplace listing.
- New `.agents/plugins/marketplace.json` declares this repo as a single-plugin marketplace named `avansaber-tailtest`. Users can now register the plugin in one command: `codex plugin marketplace add avansaber/tailtest-codex`. The existing `git clone` + `init.sh` flow continues to work unchanged.
- **Important honest framing:** marketplace install replaces only the `git clone` step. Users still need to run `init.sh` per project for hooks to fire, because Codex's `plugin_hooks` feature (which would auto-register plugin-bundled hooks) is still in development upstream. When that ships stable, init.sh will be retired. Until then, both install paths require the per-project init step.

**Skills polish (Phase D):**
- All 5 skill files in `skills/tailtest/` got their frontmatter descriptions rewritten to the "When the agent needs to (1)... (2)... (3)..." pattern used by marketplace-quality plugins. This improves how the skills score in Codex's `@`-mention picker against natural-language user phrases. File bodies are unchanged.

## [4.7.0] -- 2026-04-25

Adversarial test mode (V13). 380 tests.

**New depth tier `adversarial`:** alongside `simple` / `standard` / `thorough`, set `"depth": "adversarial"` in `.tailtest/config.json` to bias scenario generation toward adversarial categories. Generates 8-12 scenarios per file, nearly all probing breakage paths rather than confirming correctness.

**New rule R15:** every SCENARIO PLAN at standard or higher depth now includes a minimum count of adversarial scenarios labelled `[adversarial: <category>]`. Required count per depth: simple=0, standard >=2, thorough >=4, adversarial 8-12. Skip categories that genuinely do not apply (state which were skipped and why).

**8 adversarial scenario categories:** boundary inputs (`MAX_INT`, `MIN_INT`, empty, single-element, unicode, null bytes, malformed UTF-8), format / injection (path traversal, regex specials, shell metacharacters, SQL fragments), type confusion (wrong type passed), concurrent state (race conditions, shared mutable state), time / locale edges (DST, leap year, timezone shifts), error handling under partial failures (network mid-call fail, disk full, EINTR), resource exhaustion (very large input, deeply nested, many file descriptors), off-by-one logic (boundary indices, fence-post errors).

**New skill verb `tailtest-hunt <file>`:** forces an adversarial pass on a specific file regardless of project depth. Writes to a separate hunt test file (`tests/test_<basename>_hunt.py` etc.) so the hunt does not contaminate the main test suite. R12 classification applied to any failures.

**Discovery context:** V13 was developed after the V13 outreach pilot 2026-04-23, where stock tailtest produced 0 real bugs from 90 passing coverage tests across 6 repos but the same plugin produced 25 distinct real bugs once an adversarial prompt was added. V13 bakes that adversarial layer into the product so every user gets bug-hunting capability without writing custom prompts.

## [4.6.0] -- 2026-04-23

Install helper + docs clarity. No code or detection changes.

**New:** `scripts/init.sh` -- run inside any project to set up tailtest in that project. Creates `.codex/hooks.json` pointing at the plugin's hook scripts; idempotent; writes a `.hooks.json.tailtest` sidecar instead of overwriting existing config.

**Docs:** README and tailtest.com/docs/codex install sections rewritten. New three-step flow: (1) clone plugin once, (2) enable `codex_hooks` feature flag once, (3) run `init.sh` inside each project. Replaces the previous ambiguous "copy two files" instructions.

**Why:** live Codex TUI validation on 2026-04-23 surfaced that users following the previous docs could end up with scripts installed but hooks not firing, because the per-project `.codex/hooks.json` step was easy to miss. The init helper closes that gap; the manual path is still documented as a fallback.

**Detection / rule / hook code unchanged from v4.5.0.** 348 tests still passing.

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
