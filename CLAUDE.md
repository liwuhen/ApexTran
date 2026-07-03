# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Tooling is `uv` (Python) + `pnpm` (docs site). `make help` lists all targets.

```bash
make install              # uv sync + pnpm website deps + prek (pre-commit) hooks
uv sync                   # dependencies only

uv run ApexTran cli         # interactive REPL
uv run ApexTran run "msg"   # one-shot: single turn through the full pipeline, then exit
uv run ApexTran gateway     # start configured channel listeners (Telegram, Feishu)

uv run ruff check .       # lint        (line length 120)
uv run ruff format .      # format
uv run mypy backend       # type-check  (skill scripts are excluded)
uv run pytest -q          # tests
make check                # uv.lock validation + prek + mypy in one shot
```

Run a single test / module:

```bash
uv run pytest tests/test_framework.py -q
uv run pytest tests/test_framework.py::test_name -q
```

`make test` runs pytest with `--doctest-modules` (docstrings in `backend/` are executable tests). `make test-all` runs the suite across Python 3.12/3.13/3.14 via uv-managed interpreters. Requires **Python 3.12+** (the code uses PEP 695 `type` syntax).

## Architecture

**Hook-first turn loop.** Every inbound message — from any channel — runs through one pluggy pipeline. Each stage is a hook point, so shipped behavior is just the default plugins; overriding a stage never means forking the core:

```
resolve_session → load_state → build_prompt → run_model → save_state → render_outbound → dispatch_outbound
```

- **The hook contract** is `backend/hooks/hookspecs.py` (`ApexTranHookSpecs`); the built-in implementations are `backend/hooks/hook_impl.py`. Read these two first.
- **The runtime** is `backend/app/framework.py` (`ApexTranFramework`). `process_inbound()` drives a turn; hooks are dispatched through a hook-runtime abstraction (`call_many_sync` / firstresult), not by calling `hook.*` directly.
- **Plugin precedence: last registered wins.** Built-ins register first (`name="builtin"`), then external plugins from the `ApexTran` entry-point group (`importlib.metadata.entry_points(group="ApexTran")`). A later plugin overrides a default for `firstresult` hooks. There are no privileged code paths.
- `run_model` and `run_model_stream` are **mutually exclusive** — implement one, not both. `firstresult=True` hooks (`resolve_session`, `load_state`, `build_prompt`, `run_model*`, `provide_tape_store`, `build_tape_context`) take the first non-None result.

**Channels share the pipeline.** `backend/channels/` defines the `Channel` abstraction plus CLI, Telegram, and Feishu adapters (provided via the `provide_channels` hook). An agent tuned in the terminal behaves identically in a group chat. The interactive CLI UI lives in `channels/cli.py` (prompt_toolkit full-screen TUI) + `channels/renderer.py` (rich rendering).

**Extending — two mechanisms:**
- **Plugins** = code: any object with `@hookimpl`-decorated methods (`from backend import hookimpl`), shipped as a package and registered under `[project.entry-points."ApexTran"]`. Plugin dependencies install into a *separate* uv project at `~/.ApexTran/ApexTran-project` (override `ApexTran_PROJECT`), managed by `ApexTran install` / `ApexTran update` — not the main venv.
- **Skills** = data: a `SKILL.md` with validated frontmatter, discovered by `backend/skills/skills.py` and loaded on demand instead of imported. Bundled skills live in `backend/skills/`.

**State & tapes.** Per-session conversation state is recorded via a tape store (`provide_tape_store` hook; `backend/memory/`). An `AGENTS.md` present in the workspace is auto-folded into the system prompt.

## Conventions & gotchas

- **Distribution name is `ApexTran`; the importable package is `backend`** (not `ApexTran`). The console script is `ApexTran = "backend.__main__:app"`. Import from `backend.*`.
- **The pluggy hook namespace and the entry-point group are both `"ApexTran"`** (`ApexTran_HOOK_NAMESPACE`). External plugins must register under entry-point group `ApexTran`.
- **Runtime config is read from `ApexTran_*` env vars** (pydantic settings; see `env.example`) — e.g. `ApexTran_MODEL` (`provider:model`), `ApexTran_API_KEY`, `ApexTran_API_BASE`, `ApexTran_MAX_STEPS`, `ApexTran_HOME` (`~/.ApexTran`). Keep secrets in `.env`.
- **CLI internal-command mode:** lines beginning with `/` are commands, not chat (`/help`, `/skill name=...`, `/fs.read path=README.md`).
- **Version is derived from git tags** via hatch-vcs; `backend/_version.py` is the generated-but-tracked version source — do not treat it as a build artifact to delete.
- Commit style: Conventional Commits (`feat:`, `fix:`, `chore:`…); keep commits focused.

The docs site is in `website/` (Astro/pnpm: `make docs` to serve, `make docs-build` to build); the web UI is in `frontend/`. Tests are in `tests/`.
