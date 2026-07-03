# Contributing to ApexTran

Thanks for taking the time to contribute — every bug report, fix, and doc tweak helps.

## Ways to contribute

- **Report bugs.** Open an issue with your OS, your setup, and the exact steps to reproduce.
- **Fix bugs / build features.** Browse the open issues; anything tagged `help wanted` is fair game.
- **Improve the docs.** README, docstrings, and the site under `website/` can always use love.
- **Send feedback.** Propose features as issues — explain the use case and keep the scope tight.

## Local setup

You'll need [`uv`](https://docs.astral.sh/uv/) and Git installed.

1. Fork the repo and clone your fork:

   ```bash
   git clone git@github.com:YOUR_NAME/ApexTran.git
   cd ApexTran
   ```

2. Install the environment (Python deps, docs deps, and pre-commit hooks):

   ```bash
   make install
   ```

   If you only need the Python side, `uv sync` is enough.

3. Create a working branch:

   ```bash
   git checkout -b feat/short-description
   ```

## Before you open a PR

Run the checks locally:

```bash
make check     # lock validation + ruff + mypy
make test      # pytest (with doctests)
```

If your change spans multiple Python versions, run the matrix (uv fetches each
interpreter automatically):

```bash
make test-all
```

Then commit with a [Conventional Commit](https://www.conventionalcommits.org/) message and push:

```bash
git add .
git commit -m "feat: short description of the change"
git push origin feat/short-description
```

## Pull request guidelines

- Include tests for new behavior, and update the docs when commands or behavior change.
- Keep each PR focused on one thing.
- Describe what changed, why, and how you verified it.
