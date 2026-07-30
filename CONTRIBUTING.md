# Contributing to tailtest-codex

Thanks for contributing to tailtest-codex. Here is how to get a change in.

## Code of conduct

Participation in this project is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).

## Filing issues

Use the [issue tracker](https://github.com/avansaber/tailtest-codex/issues). When filing a bug, please include:

- tailtest-codex version (from the `README.md` badge or `CHANGELOG.md`)
- Codex CLI version (must be 0.129.0 or newer)
- Operating system and version (Windows, macOS, or Linux)
- Repro steps, expected behavior, and actual behavior
- Relevant excerpts from `.tailtest/reports/latest.json` if applicable

## Submitting changes

1. Fork the repo and create a topic branch off `main`.
2. Make your change. Keep commits focused and the diff small where possible.
3. Run the validation commands below and report the platform-specific result; do not imply unrun platforms passed.
4. Open a pull request against `main` with a clear description of what changed and why.

Contributor email is not required, and the project does not collect Co-Authored-By signing data.

## Running tests

```bash
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
```

To run a single test file or test:

```bash
pytest tests/test_post_tool_use.py -q
pytest tests/test_post_tool_use.py::test_specific_case -q
```

## Adding a new R rule

The R1-R15 rule layer is documented in `AGENTS.md` at the repo root. New rules should extend that document with the same shape used by existing rules. Supporting code lives under `hooks/lib/`.

## Adding a new language baseline or framework template

Language and framework detection drives R2 and R3 behavior. Detection and runner logic lives in `hooks/lib/runners.py` and `hooks/lib/scanner.py`. Add detection for the new runner there, then add tests under `tests/` that mirror existing runner tests.

## Release process

Releases are tagged from `main`. Update `CHANGELOG.md` in the same PR as the user-visible change, following the existing per-version section shape. Maintainers handle the GitHub Release upload after a tag lands.

## License of contributions

By submitting changes you agree they are MIT-licensed under the project [LICENSE](LICENSE).
