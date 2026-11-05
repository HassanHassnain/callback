.PHONY: setup preflight smoke catalog test lint provision status deploy verify-infra deploy-sandbox verify-sandbox teardown-plan

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

provision:
	uv run python infra/provision.py up

status:
	uv run python infra/provision.py status

deploy:
	uv run python infra/deploy.py

verify-infra:
	uv run python infra/deploy.py --verify

deploy-sandbox:
	uv run python infra/setup_sandbox.py

verify-sandbox:
	uv run python infra/verify_sandbox.py

teardown-plan:
	uv run python infra/provision.py down
