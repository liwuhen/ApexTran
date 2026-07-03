# Repository Guidelines

## Project Structure & Module Organization

Application code lives under `backend/`:

- `backend/__main__.py` — Typer CLI entrypoint (`ApexTran = "backend.__main__:app"`).
- `backend/app/framework.py` — turn orchestration, plugin loading, and outbound routing.
- `backend/architecture/schemas/` — hook contracts (`hookspecs.py`) and built-in hook
  implementations (`hook_impl.py`).
- `backend/architecture/agent/` — agent loop, settings, and auth.
- `backend/architecture/channels/` — channel abstractions plus CLI, Telegram, and Feishu adapters.
- `backend/architecture/skills/` & `backend/architecture/tool/` — skill discovery and the tool registry.
- `backend/cli/` — install/gateway/update plugin-management commands.
- `backend/skills/` — skills bundled with ApexTran.

Tests live in `tests/`. The documentation site lives in `website/`; the web UI lives in `frontend/`.

## Build, Test, and Development Commands

- `uv sync` — install or update dependencies.
- `make install` — sync dependencies and install `prek` (pre-commit) hooks.
- `uv run ApexTran chat` — interactive CLI.
- `uv run ApexTran gateway` — start channel listeners.
- `uv run ApexTran run "hello"` — run a single message through the full pipeline.
- `uv run ruff check .` — lint.
- `uv run mypy backend` — static type checks.
- `uv run pytest -q` — run the test suite.
- `make check` — lock validation, lint, and typing in one shot.
- `make docs` / `make docs-build` — serve or build the docs site in `website/`.

## Coding Style & Naming Conventions

- Python 3.12+, 4-space indentation, type hints on new or modified logic.
- `snake_case` for modules/functions/variables, `PascalCase` for classes, `UPPER_CASE` for constants.
- Keep functions focused and side-effect-light; prefer composition over hidden state.
- Format and lint with Ruff (line length 120).

## Testing Guidelines

- Framework: `pytest` (with `pytest-asyncio` for async paths).
- Name test files `tests/test_<feature>.py` and use behavior-oriented test names.
- When you change runtime behavior, cover hook precedence, the turn lifecycle, and
  channel/CLI behavior in the same change.

## Commit & Pull Request Guidelines

- Use Conventional Commits: `feat:`, `fix:`, `docs:`, `chore:`, etc.
- Keep commits focused; don't mix unrelated refactors with behavior changes.
- PRs should state what changed and why, which modules/commands are affected, and the
  verification performed (`ruff`, `mypy`, `pytest`).

## Security & Configuration Tips

- Keep secrets in `.env`; never commit credentials.
- Runtime settings come from `ApexTran_*` variables — e.g. `ApexTran_MODEL`, `ApexTran_API_KEY`,
  `ApexTran_API_BASE`. See `env.example` for the full list.
- Provider-specific keys (e.g. `OPENROUTER_API_KEY`) may still be read by downstream SDKs.
- Telegram needs `ApexTran_TELEGRAM_TOKEN`; restrict access with `ApexTran_TELEGRAM_ALLOW_USERS`
  and `ApexTran_TELEGRAM_ALLOW_CHATS`.
