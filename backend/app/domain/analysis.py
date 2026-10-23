"""Bounded historical research inputs, distinct from production policy pricing."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    ticker: str = Field(pattern=r"^c\d{4}$")
    valuation_date: str = Field(pattern=r"^2026-\d{2}-\d{2}$")
    strike_ratio: Literal[0.95, 1.0, 1.05] = 1.0
    quantity: float = Field(default=100, gt=0, le=100000)
    budget: float = Field(default=5000, ge=0, le=1e10)
    deductible: float = Field(default=0, ge=0, le=10000)
    payout_cap: float | None = Field(default=None, ge=0, le=1e10)
    shocks: list[float] = Field(default_factory=lambda: [-10, -5, 0, 5], min_length=1, max_length=9)

    @field_validator("shocks")
    @classmethod
    def bounded_shocks(cls, values):
        if any(not -50 <= v <= 50 for v in values) or len(set(values)) != len(values):
            raise ValueError("价格冲击须在 -50% 至 50% 之间且不能重复")
        return values
