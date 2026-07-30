# tailtest-codex -- AI software testing for OpenAI Codex CLI

[![License: MIT](https://img.shields.io/badge/License-MIT-emerald.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-437_passing_(Windows)-emerald)](https://github.com/avansaber/tailtest-codex)
[![Manifest version](https://img.shields.io/badge/manifest-4.9.1-blue)](.codex-plugin/plugin.json)
[![Validation](https://img.shields.io/badge/validated-Windows_%7C_WSL%2FLinux-lightgrey)](https://github.com/avansaber/tailtest-codex)
[![Codex CLI](https://img.shields.io/badge/Codex_CLI-0.129.0%2B-purple)](https://developers.openai.com/codex)

**tailtest-codex** is the open-source AI software testing layer for [OpenAI Codex CLI](https://developers.openai.com/codex). It runs inside the build loop: `PostToolUse` watches the supported `Bash`, `apply_patch`, `Edit`, and `Write` events, while `Stop` catches validated pending work at the turn boundary. Together they queue changed files, generate scenarios via the R1-R15 rule layer, run them with your project's existing test runner, and surface failures back to Codex within the same turn. Hook-based. Deterministic. No prompting required.

Open source (MIT), no telemetry, no SaaS account. Same R1-R15 rule layer + adversarial mode (R15) as the Claude Code, Cursor, and Cline variants.

**[Read more on tailtest.com](https://www.tailtest.com/) · [Platform overview](https://www.tailtest.com/platform/) · [Agent-edit testing deep dive](https://www.tailtest.com/platform/agent-edits/) · [Codex docs](https://www.tailtest.com/docs/codex/)**

---

## Install

For current Codex versions, the marketplace path is recommended:

```bash
codex plugin marketplace add avansaber/tailtest-codex
codex plugin add tailtest@avansaber-tailtest
```

Start a new Codex session and review/approve Tailtest's `SessionStart`, `PostToolUse`, and `Stop` hook commands when prompted. On current Codex, the plugin hook manifest activates these hooks; this path does **not** require a per-project `.codex/hooks.json`.

### Direct clone (manual fallback)

The direct-clone path remains available when you need a local checkout or manual hook setup:

```bash
git clone https://github.com/avansaber/tailtest-codex ~/.codex/plugins/tailtest
cd <your-project>
bash ~/.codex/plugins/tailtest/scripts/init.sh
```

Run the initializer inside each target project. It writes absolute hook commands, is idempotent, and preserves a conflicting existing `.codex/hooks.json` by writing `.codex/hooks.json.tailtest` for manual merge.

### Older Codex CLI versions

Codex CLI versions before 0.129.0 shipped hooks behind a feature flag. If `codex --version` reports an older release, add the following to `~/.codex/config.toml` once:

```toml
[features]
hooks = true
```

The `codex_hooks` key (used in older docs) is still accepted as a deprecated alias but emits a warning on every session start; use `hooks` going forward.

---

## How it works

1. `SessionStart` scans for runners and returns compact trusted runtime instructions as hook context. It never writes a persistent project `AGENTS.md`.
2. `PostToolUse` is registered only for canonical Codex `Bash`, `apply_patch`, `Edit`, and `Write` events. Patch-like payloads are parsed only for patch tools, including current `tool_input.command` payloads; shell commands use a bounded mtime/Git fallback. Its non-blocking response contains `hookSpecificOutput.hookEventName: "PostToolUse"` and `additionalContext`.
3. `Stop` blocks when validated pending work remains and safely persists the queue. It defers only for a current-user standalone `/tailtest defer` or an explicit no-more-tools boundary; `/tailtest defer` lasts one turn and queued work blocks again on the next user turn.

Filenames, paths, transcripts, hook payloads, and session JSON are untrusted data, not instructions. In particular, `/tailtest defer` text inside fenced or quoted content, assistant/tool output, filenames, transcripts, or other repository-derived data is never a directive.

### Validation status

At this branch revision, `python -m pytest -q` passed with 437 tests on Windows. The WSL/Linux run passed with 436 tests and 1 skipped. macOS was not rerun for this documentation update. This is branch validation evidence, not a claim of a published release, merged upstream state, green GitHub checks, or a freshly released install artifact.

---

## Quick config

Create `.tailtest/config.json` in your project root:

```json
{ "depth": "standard" }
```

Options: `simple` (2-3 scenarios), `standard` (5-8, default), `thorough` (10-15).

See [tailtest.com/docs/config](https://tailtest.com/docs/config) for all options.

---

## Other tailtest variants

Same R1-R15 rule layer, same adversarial test mode, different host integration. **This repo is the Codex CLI variant.**

- **[tailtest](https://github.com/avansaber/tailtest)** -- Claude Code plugin (hook-driven)
- **[tailtest-cursor](https://github.com/avansaber/tailtest-cursor)** -- Cursor plugin (hook-driven)
- **[tailtest-codex](https://github.com/avansaber/tailtest-codex)** -- Codex CLI plugin (hook-driven; this repo)
- **[tailtest-cline](https://github.com/avansaber/tailtest-cline)** -- Cline plugin (MCP-driven; reaches 8+ editors via Cline's host coverage)

See [tailtest.com/demo/codex](https://tailtest.com/demo/codex) for a live walkthrough of this variant, [tailtest.com/comparison](https://tailtest.com/comparison) for a feature matrix across all four, or [tailtest.com](https://tailtest.com) for the project home.

---

## License

MIT
