# tailtest for Codex CLI

tailtest blocks Codex at the end of every turn and asks it to write and run tests before continuing -- automatically, with no prompting.

**[Full documentation at tailtest.com/docs/codex](https://tailtest.com/docs/codex)**

---

## Install

Requires Codex CLI 0.129.0 or newer (hooks are stable and on by default in this range).

```bash
# One-time setup (any terminal):
git clone https://github.com/avansaber/tailtest-codex ~/.codex/plugins/tailtest

# Per-project setup (run inside each project where you want tailtest active):
cd <your-project>
bash ~/.codex/plugins/tailtest/scripts/init.sh
```

That's it. Start a `codex` session in the project and tailtest fires on every turn.

The init script creates `.codex/hooks.json` in your project pointing at the tailtest hook scripts. It is idempotent (safe to re-run) and never overwrites an existing `hooks.json` with different content; it writes a `.codex/hooks.json.tailtest` sidecar instead for manual merging.

### Marketplace install (alternative)

The repo also ships as a Codex marketplace, so you can register it with one command instead of `git clone`:

```bash
codex plugin marketplace add avansaber/tailtest-codex
```

Then enable the plugin from inside a Codex session (the interactive `/plugins` menu) or by adding this entry to `~/.codex/config.toml`:

```toml
[plugins."tailtest@avansaber-tailtest"]
enabled = true
```

You still need to run `bash ~/.codex/plugins/tailtest/scripts/init.sh` per project for hooks to fire, because Codex's `plugin_hooks` feature (which lets plugins register hooks automatically) is currently in development. Once that ships stable, the init step will go away. Until then, marketplace install just replaces the `git clone` step and is a forward-compat path.

### Older Codex CLI versions

Codex CLI versions before 0.129.0 shipped hooks behind a feature flag. If `codex --version` reports an older release, add the following to `~/.codex/config.toml` once:

```toml
[features]
hooks = true
```

The `codex_hooks` key (used in older docs) is still accepted as a deprecated alias but emits a warning on every session start; use `hooks` going forward.

---

## How it works

1. `SessionStart` hook scans for runners and injects `AGENTS.md`
2. `PostToolUse` hook fires after every `apply_patch` or shell-style tool call: parses the patch (or sweeps mtimes when the payload doesn't surface paths), queues qualified source files, and surfaces them to the agent as mid-turn context
3. `Stop` hook sweeps any leftovers at end of turn and prompts the agent to write tests before continuing

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
