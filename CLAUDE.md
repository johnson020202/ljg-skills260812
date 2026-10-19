# Repository guide

This fork is `johnson020202/ljg-skills260812`. The original author attribution and MIT license remain unchanged. Current installation, dependency, and verification instructions are in `README.md`.

## Layout

- `skills/ljg-*/SKILL.md`: self-contained skill definitions and invocation contracts.
- Each skill owns its `Tools/`, `scripts/`, `assets/`, references, and regression tests as applicable.
- `.claude-plugin/`: collection metadata; plugin, marketplace, and plugin-entry versions must agree.
- `scripts/setup.py`: checkout-local dependency and browser setup.
- `scripts/check.py`: repository contracts, syntax checks, and all checked-in test suites; `--format all` also checks a complete generated Markdown distribution.
- `scripts/build_format.py`: offline, input-preserving format builds into a new directory; the format-neutral `fix-ljg-org-to-md` skill uses this entrypoint.
- `.github/workflows/check.yml`: Linux and macOS validation.

The README inventory is checked against all actual skill directories. Do not use a separate hardcoded skill list here.

## Development commands

Run from the repository root:

```sh
python3 scripts/setup.py
python3 scripts/check.py --format all
```

`python3 scripts/check.py --static` is a limited syntax/contract check, not a replacement for regression tests. Detailed results are in `.cache/check-results.json`.

Bun modules use their own frozen lockfiles. The Python renderer uses `skills/ljg-book-poster/requirements.txt` in the checkout `.venv`. Test browsers are isolated under `.cache/ms-playwright`; different Playwright versions require matching browser revisions.

## Outputs and installation

Skill tools must be resolved from the actual loaded skill directory; installations may be global or project-local. Follow each skill's output contract rather than assuming all outputs belong in Downloads or all notes use the same format.

Repository verification does not copy skills to the user's installation or publish a release. The publishing skill has separate identity, clean-worktree, and explicit branch safeguards. `master` is the source branch; `md` is a generated release branch, not a safe location for untracked manual patches.
