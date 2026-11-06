"""Persistent app daily budget, reserved before requests using live catalog rates."""

import asyncio
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path


class BudgetExceeded(RuntimeError):
    pass


def rates(model, unit="token"):
    result = {}
    for side in ("input_modalities", "output_modalities"):
        for modality in model.get(side, []):
            for price in modality.get("pricing", []):
                if price.get("unit") == unit:
                    result[price["type"]] = Decimal(price["cost_usd"])
    return result


class Budget:
    def __init__(self, path, limit_usd="20"):
        self.path = Path(path)
        self.limit = Decimal(limit_usd)
        self.lock = asyncio.Lock()
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data))
        temporary.chmod(0o600)
        temporary.replace(self.path)

    async def reserve(self, model, body, *, audio_seconds=None):
        pricing = rates(model, "second" if audio_seconds is not None else "token")
        if not pricing:
            raise BudgetExceeded("No live pricing for this route")
        if audio_seconds is not None:
            if not 0 < audio_seconds <= 90:
                raise BudgetExceeded("Audio requires a bounded duration")
            amount = Decimal(str(audio_seconds)) * sum(pricing.values())
        else:
            context = max((m.get("supported_inputs", {}).get("max_context_length", {}).get("value", 0)
                           for m in model.get("input_modalities", [])), default=0)
            if not context:
                raise BudgetExceeded("No catalog input bound for this route")
            prompt = pricing.get("prompt", max(pricing.values()))
            output = pricing.get("completion", max(pricing.values()))
            amount = (Decimal(context) * prompt + Decimal(body.get("max_completion_tokens", 2048)) * output)
            amount *= max(1, len(body.get("questions", {})))
        async with self.lock:
            day = datetime.now(UTC).date().isoformat()
            if self.data.get("day") != day:
                self.data = {"day": day, "charged_usd": "0", "requests": 0}
            current = Decimal(self.data["charged_usd"])
            if current + amount > self.limit:
                raise BudgetExceeded("Application daily inference budget reached")
            self.data["charged_usd"] = str(current + amount)
            self.data["requests"] += 1
            self.save()
        return {"reserved": amount, "pricing": pricing, "day": day, "audio": audio_seconds is not None}

    async def settle(self, reservation, data):
        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        pricing = reservation["pricing"]
        actual = None
        if not reservation["audio"] and "prompt" in pricing and "prompt_tokens" in usage and "completion_tokens" in usage:
            actual = Decimal(usage["prompt_tokens"]) * pricing["prompt"] + Decimal(usage["completion_tokens"]) * pricing["completion"]
        # Missing/ambiguous usage or a failed transport retains the full bound.
        if actual is not None:
            async with self.lock:
                if self.data.get("day") == reservation["day"]:
                    self.data["charged_usd"] = str(Decimal(self.data["charged_usd"]) - reservation["reserved"] + actual)
                    self.save()
        return {"cost_estimate_usd": str(actual) if actual is not None else None,
                "budget_charge_usd": str(actual if actual is not None else reservation["reserved"]),
                "cost_source": "response_tokens_x_live_catalog" if actual is not None else "conservative_catalog_bound"}
