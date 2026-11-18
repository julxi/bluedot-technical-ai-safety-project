# Project checks. `make check` must pass before code changes are finished (docs/CODING.md
# §Testing and checks); it verifies and changes nothing. `make format` fixes what it can.

.PHONY: check
check:
	uv run ruff format --check src tests tasks
	uv run ruff check src tests tasks
	uv run basedpyright
	uv run pytest -q

.PHONY: format
format:
	uv run ruff check --fix src tests tasks
	uv run ruff format src tests tasks

.PHONY: test
test:
	uv run pytest -q
