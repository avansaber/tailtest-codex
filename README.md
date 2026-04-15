# tailtest for Codex CLI

**You build. Codex builds. tailtest makes sure it works.**

tailtest is a Codex CLI plugin that automatically generates and runs tests for every file Codex creates or modifies. No configuration required for Python and TypeScript projects -- just install and start building.

---

## Requirements

- Python 3.9+
- Codex CLI 0.120+
- `codex_hooks = true` in your Codex config
- macOS or Linux (Windows hooks not supported)

---

## Install

```sh
# Step 1: Copy plugin files
git clone https://github.com/avansaber/tailtest-codex ~/.codex/plugins/tailtest

# Step 2: Register in marketplace
# Add to ~/.agents/plugins/marketplace.json:
{
  "plugins": [{ "name": "tailtest", "path": "~/.codex/plugins/tailtest" }]
}

# Step 3: Enable hook support
# Add to ~/.codex/config.toml (or <project>/.codex/config.toml):
[features]
codex_hooks = true

# Step 4: Register hooks in your project
cp ~/.codex/plugins/tailtest/.codex/config.toml <project>/.codex/config.toml
cp ~/.codex/plugins/tailtest/hooks/hooks.json <project>/.codex/hooks.json

# Restart Codex. Then just build.
```

---

## How it works

**SessionStart hook:** When Codex starts a session, tailtest scans your project for test runners, detects your test style, and injects `AGENTS.md` so Codex knows the test workflow.

**Stop hook:** At the end of every Codex agent turn, tailtest sweeps the project for files whose modification time is newer than when the turn started. Any new or changed source files are queued for test generation. Codex gets a `decision: block` response with an instruction to write tests before continuing.

**AGENTS.md:** The instruction file that drives the entire test generation cycle -- scenario selection, test writing, execution, fix loop, and reporting.

---

## Configuration

**Depth** (`<project>/.tailtest/config.json`):
```json
{ "depth": "thorough" }
```
Options: `"minimal"` (happy path only), `"standard"` (default, happy + one edge case), `"thorough"` (full scenario suite).

**Ramp-up limit** (for existing projects):
```json
{ "ramp_up_limit": 20 }
```
Controls how many existing untested files tailtest queues on first run. Default: 10.

**Ignore patterns** (`<project>/.tailtest-ignore`):
```
scripts/
migrations/
src/legacy/
```
Uses gitignore-style patterns. Files matching these patterns are never queued.

---

## Supported languages

| Language   | Extension(s)          | Runner detection          | Runner required? |
|------------|-----------------------|---------------------------|------------------|
| Python     | `.py`                 | pytest, unittest          | No               |
| TypeScript | `.ts`, `.tsx`         | jest, vitest              | No               |
| JavaScript | `.js`, `.jsx`, `.mjs` | jest, vitest              | No               |
| Go         | `.go`                 | `go test`                 | Yes              |
| Rust       | `.rs`                 | `cargo test`              | Yes              |
| Ruby       | `.rb`                 | rspec, minitest           | Yes              |
| PHP        | `.php`                | phpunit                   | Yes              |
| Java       | `.java`               | maven, gradle             | Yes              |

"Runner required" means tailtest will not queue files for that language unless it detected the runner during SessionStart. Python, TypeScript, and JavaScript can queue without an explicit runner.

---

## Differences from the Claude Code plugin

| Feature                | tailtest for Claude Code         | tailtest for Codex CLI              |
|------------------------|----------------------------------|-------------------------------------|
| File detection         | PostToolUse hook (per tool call) | Stop hook (mtime sweep, per turn)   |
| Hook file location     | `.claude/hooks/`                 | `<project>/.codex/hooks.json`       |
| Install method         | `claude mcp add`                 | Clone + marketplace.json            |
| Instruction file       | `CLAUDE.md`                      | `AGENTS.md`                         |
| Feature flag required  | No                               | `codex_hooks = true`                |
| Repo                   | avansaber/tailtest               | avansaber/tailtest-codex            |

---

## Commands

| Command              | What it does                                              |
|----------------------|-----------------------------------------------------------|
| `/tailtest <file>`   | Manually queue a specific file for test generation        |
| `/summary`           | Print a plain-text summary of session test results        |
| `/tailtest off`      | Pause automatic test generation for this session          |
| `/tailtest on`       | Resume automatic test generation after a pause            |

---

## Troubleshooting

**"No test output after Codex writes a file"**

Check that `codex_hooks = true` is in your `.codex/config.toml`. Without this flag, Codex does not call the Stop hook and no file detection occurs.

**"Codex seems stuck in a loop"**

tailtest uses a `stop_hook_active` guard to prevent infinite loops. If you see repeated test prompts without progress, check that `hooks.json` is correctly placed in your project root (not in a subdirectory).

**"Windows support?"**

Codex hooks are not supported on Windows. tailtest for Codex CLI requires macOS or Linux.

**"Rust/Go/Java files not queuing"**

These languages require a detected runner. If SessionStart didn't find `Cargo.toml`, `go.mod`, or a Maven/Gradle file in your project, those files will be silently skipped. Verify your project structure includes the standard manifest file.

---

## Security

tailtest hooks run entirely on your local machine. No data is sent to external servers. Session state is written to `.tailtest/session.json` in your project directory. The `.tailtest/` directory is auto-added to `.gitignore` on first run.

See [SECURITY.md](SECURITY.md) for responsible disclosure information.

---

## License

Apache-2.0. See [LICENSE](LICENSE).
