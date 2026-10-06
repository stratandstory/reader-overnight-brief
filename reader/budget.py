"""Token and cost accounting per stage, with a hard per-run ceiling."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from .config import Settings

CACHE_WRITE = 1.25  # 5-minute cache writes cost 1.25x the input price
CACHE_READ = 0.10   # cache reads cost 0.1x unless the price row gives a cache_read rate (Fable 5.1: $0.25/MTok)
CHARS_PER_TOKEN = 3.5  # conservative estimate for English news text


@dataclass
class StageUsage:
    stage: str
    model: str
    calls: int = 0
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    cost: float = 0.0


class Budget:
    def __init__(self, settings: Settings, max_usd: float):
        self.settings = settings
        self.max_usd = max_usd
        self.rows: dict[tuple[str, str], StageUsage] = {}
        self.projected: list[dict] = []  # dry-run estimates
        self._lock = threading.Lock()

    def cost_of(self, model: str, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0) -> float:
        p = self.settings.price(model)
        return (
            input_tokens * p["input"]
            + output_tokens * p["output"]
            + cache_read * p.get("cache_read", p["input"] * CACHE_READ)
            + cache_write * p["input"] * CACHE_WRITE
        ) / 1_000_000

    def record(self, stage: str, model: str, usage) -> float:
        inp = usage.input_tokens or 0
        out = usage.output_tokens or 0
        cr = usage.cache_read_input_tokens or 0
        cw = usage.cache_creation_input_tokens or 0
        cost = self.cost_of(model, inp, out, cr, cw)
        with self._lock:
            row = self.rows.setdefault((stage, model), StageUsage(stage, model))
            row.calls += 1
            row.input += inp
            row.output += out
            row.cache_read += cr
            row.cache_write += cw
            row.cost += cost
        return cost

    @staticmethod
    def tokens_for(chars: int) -> int:
        return int(chars / CHARS_PER_TOKEN) + 1

    def estimate(self, model: str, input_chars: int, output_tokens: int) -> float:
        return self.cost_of(model, self.tokens_for(input_chars), output_tokens)

    def project(self, stage: str, model: str, input_chars: int, output_tokens: int, calls: int = 1, note: str = "") -> None:
        self.projected.append({
            "stage": stage, "model": model, "calls": calls,
            "input": self.tokens_for(input_chars), "output": output_tokens,
            "cost": self.estimate(model, input_chars, output_tokens), "note": note,
        })

    @property
    def spent(self) -> float:
        with self._lock:
            return sum(r.cost for r in self.rows.values())

    def fits(self, estimate: float, reserve: float = 0.0) -> bool:
        return self.spent + estimate + reserve <= self.max_usd

    def summary_rows(self) -> list[dict]:
        order = ["screen", "find", "check", "write", "audit"]
        rows = sorted(self.rows.values(), key=lambda r: (order.index(r.stage) if r.stage in order else 99, r.model))
        return [r.__dict__.copy() for r in rows]
