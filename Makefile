.PHONY: setup preflight smoke catalog test lint

setup:
	uv sync

preflight:
	uv run python scripts/check_setup.py

smoke:
	uv run python scripts/si_smoke.py

catalog:
	uv run python scripts/si_smoke.py --catalog-only

test:
	uv run pytest -q

lint:
	uv run ruff check .
