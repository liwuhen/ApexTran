# ApexTran task runner. Run `make` or `make help` to list targets.

SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.ONESHELL:
.DEFAULT_GOAL := help

# Python versions exercised by `make test-all`
PYTHONS := 3.12 3.13 3.14

.PHONY: help install check vulture test test-all clean build publish release docs docs-build docs-preview docker-build up down logs

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Set up the dev environment: venv, website deps, pre-commit hooks
	@echo "🍦 Syncing the virtual environment with uv"
	uv sync
	@echo "🍦 Installing website dependencies"
	pnpm --dir website install --frozen-lockfile
	@echo "🍦 Installing pre-commit hooks"
	uv run prek install

check: ## Verify the lock file, lint, and type-check
	@echo "🍦 Verifying uv.lock is in sync with pyproject.toml"
	uv lock --locked
	@echo "🍦 Running pre-commit hooks"
	uv run prek run -a
	@echo "🍦 Type-checking backend"
	uv run mypy backend

vulture: ## Report unused code
	uv run prek run vulture --hook-stage manual --all-files

test: ## Run the test suite (current Python)
	uv run python -m pytest --doctest-modules

test-all: ## Run the test suite across all supported Python versions (uv-managed)
	@for v in $(PYTHONS); do \
		echo "🍦 pytest on Python $$v"; \
		UV_PROJECT_ENVIRONMENT="$(CURDIR)/.venvs/py$$v" \
			uv run --python "$$v" python -m pytest --doctest-modules tests; \
	done

clean: ## Remove build artifacts
	rm -rf dist

build: clean ## Build the wheel and sdist
	uvx --from build pyproject-build --installer uv

publish: ## Publish to PyPI (requires credentials)
	uvx twine upload --repository-url https://upload.pypi.org/legacy/ dist/*

release: build publish ## Build then publish

docs: ## Serve the docs site with live reload
	pnpm --dir website dev --host

docs-build: ## Build the docs site (fails on warnings)
	pnpm --dir website build

docs-preview: ## Preview the production docs build
	pnpm --dir website preview --ip 0.0.0.0

docker-build: ## Build the container image
	docker compose build

up: ## Start the container stack in the background
	docker compose up -d

down: ## Stop and remove the container stack
	docker compose down

logs: ## Follow container logs
	docker compose logs -f
