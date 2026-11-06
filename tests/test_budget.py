import asyncio
from decimal import Decimal

import pytest

from services.control.budget import Budget, BudgetExceeded


MODEL = {"input_modalities": [{"supported_inputs": {"max_context_length": {"value": 1000}},
    "pricing": [{"type": "prompt", "unit": "token", "cost_usd": "0.0001"}]}],
    "output_modalities": [{"pricing": [{"type": "completion", "unit": "token", "cost_usd": "0.0002"}]}]}


def test_reservation_survives_restart_and_blocks_overspending(tmp_path):
    async def run():
        path = tmp_path / "budget.json"
        first = Budget(path, "0.2")
        await first.reserve(MODEL, {"max_completion_tokens": 100})
        recovered = Budget(path, "0.2")
        with pytest.raises(BudgetExceeded):
            await recovered.reserve(MODEL, {"max_completion_tokens": 100})
        assert Decimal(recovered.data["charged_usd"]) == Decimal("0.12")
        assert path.stat().st_mode & 0o777 == 0o600

    asyncio.run(run())


def test_response_tokens_refund_unused_bound_but_missing_usage_does_not(tmp_path):
    async def run():
        budget = Budget(tmp_path / "budget.json", "1")
        reservation = await budget.reserve(MODEL, {"max_completion_tokens": 100})
        result = await budget.settle(reservation, {"usage": {"prompt_tokens": 10, "completion_tokens": 5}})
        assert Decimal(result["cost_estimate_usd"]) == Decimal("0.002")
        reservation = await budget.reserve(MODEL, {"max_completion_tokens": 100})
        await budget.settle(reservation, None)
        assert Decimal(budget.data["charged_usd"]) == Decimal("0.122")

    asyncio.run(run())


def test_systemone_settles_billed_input_tokens_from_live_catalog_shape(tmp_path):
    async def run():
        budget = Budget(tmp_path / "budget.json", "1")
        model = {
            "input_modalities": [{"supported_inputs": {"max_context_length": {"value": 262144}}}],
            "output_modalities": [{"pricing": [{"type": "completion", "unit": "token", "cost_usd": "0.00000005"}]}],
        }
        reservation = await budget.reserve(model, {"questions": {"a": {}, "b": {}}}, decision=True)
        assert reservation["reserved"] == Decimal("0.02621440")
        result = await budget.settle(reservation, {"usage": {"input_tokens": 2000, "output_tokens": 0}})
        assert Decimal(result["budget_charge_usd"]) == Decimal("0.0001")
        assert Decimal(budget.data["charged_usd"]) == Decimal("0.0001")

    asyncio.run(run())
