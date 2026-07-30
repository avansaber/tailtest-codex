# tailtest-codex -- AI software testing for OpenAI Codex CLI

[![License: MIT](https://img.shields.io/badge/License-MIT-emerald.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-458_passing_(Windows)-emerald)](https://github.com/avansaber/tailtest-codex)
[![Version](https://img.shields.io/badge/version-4.9.1-blue)](https://github.com/avansaber/tailtest-codex/releases/latest)
[![Platform](https://img.shields.io/badge/platform-Windows_%7C_macOS_%7C_Linux-lightgrey)](https://tailtest.com/platform/agent-edits/)
[![Codex CLI](https://img.shields.io/badge/Codex_CLI-0.129.0%2B-purple)](https://developers.openai.com/codex)

**tailtest-codex** is the open-source AI software testing layer for [OpenAI Codex CLI](https://developers.openai.com/codex). It runs inside the build loop: PostToolUse + Stop hooks fire after every `apply_patch` Codex makes, queue the changed files, generate scenarios via the R1-R15 rule layer, run them with your project's existing test runner, and surface failures back to Codex within the same turn. Hook-based. Deterministic. No prompting required.

Open source (MIT), no telemetry, no SaaS account. Same R1-R15 rule layer + adversarial mode (R15) as the Claude Code, Cursor, and Cline variants -- 1,234 plugin tests total across the four hosts.

**[Read more on tailtest.com](https://www.tailtest.com/) · [Platform overview](https://www.tailtest.com/platform/) · [Agent-edit testing deep dive](https://www.tailtest.com/platform/agent-edits/) · [Codex docs](https://www.tailtest.com/docs/codex/)**

---

## Install

Requires Codex CLI 0.129.0 or newer (hooks are stable and on by default in this range).

### Marketplace install (recommended)

```bash
codex plugin marketplace add avansaber/tailtest-codex
codex plugin add tailtest@avansaber-tailtest
```

Start a new Codex session and review the three Tailtest hook commands when Codex asks you to trust them. The plugin bundle registers `SessionStart`, `PostToolUse`, and `Stop` automatically; no project hook file is required.

### Direct clone (fallback)

```bash
git clone https://github.com/avansaber/tailtest-codex ~/.codex/plugins/tailtest
cd <your-project>
bash ~/.codex/plugins/tailtest/scripts/init.sh
```

The initializer writes project-scoped `.codex/hooks.json` commands with absolute script paths. It is idempotent and never overwrites a different hook file; it writes `.codex/hooks.json.tailtest` for manual merging instead.

### Older Codex CLI versions

Codex CLI versions before 0.129.0 shipped hooks behind a feature flag. If `codex --version` reports an older release, add the following to `~/.codex/config.toml` once:

```toml
[features]
hooks = true
```

The `codex_hooks` key (used in older docs) is still accepted as a deprecated alias but emits a warning on every session start; use `hooks` going forward.

---

## How it works

1. `SessionStart` scans for runners and returns compact trusted runtime instructions as session context without writing into the project
2. `PostToolUse` matches canonical Codex `Bash`, `apply_patch`, `Edit`, and `Write` calls, parses `tool_input.command` (or sweeps mtimes), and surfaces qualified in-project source files as mid-turn context
3. `Stop` sweeps any leftovers and blocks while `.tailtest/session.json` still contains pending work

Need a strict no-more-tools boundary after a write? Include `/tailtest defer`
in that user message. Tailtest still validates and queues the change, but Stop
does not force another agent cycle; the queue resumes on the next user turn.

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
