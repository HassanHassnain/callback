.PHONY: setup smoke catalog test lint

setup:
	uv sync

smoke:
	uv run python scripts/si_smoke.py

catalog:
	uv run python scripts/si_smoke.py --catalog-only

test:
	uv run pytest -q

lint:
	uv run ruff check .
