# Quality gates. `make check` must pass before any task is marked DONE (CLAUDE.md §0.3).
.PHONY: install check lint format-check typecheck test fmt

UV := uv run

install:
	uv sync

check: lint format-check typecheck test

lint:
	$(UV) ruff check .

format-check:
	$(UV) ruff format --check .

typecheck:
	$(UV) mypy

test:
	$(UV) pytest --cov --cov-report=term

# Rewrites files: fixes auto-fixable lint findings, then formats.
fmt:
	$(UV) ruff check --fix .
	$(UV) ruff format .
