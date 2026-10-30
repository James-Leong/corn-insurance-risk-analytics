"""Decision context, regional assessment and policy APIs."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.platform import decision
from app.platform.auth import require_user
from app.repositories.market_cache import MarketCacheError

router = APIRouter(prefix="/api/v2/decision", tags=["decision-context"])
Actor = Annotated[dict, Depends(require_user)]
ProjectId = Annotated[str, Query(min_length=1, max_length=80)]


class RiskAssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    project_id: str = Field(default="PRJ-001", min_length=1, max_length=80)
    region_code: str = Field(
        pattern=r"^\d{6}$", description="中国行政区划代码；仅格式校验，不表示数据覆盖已核验"
    )
    region_name: str = Field(min_length=1, max_length=100)
    crop: Literal["maize"]
    growth_stage: Literal[
        "unknown", "seedling", "jointing", "tasseling", "grain_filling", "maturity"
    ] = "unknown"
    as_of: AwareDatetime
    hazard_types: list[Literal["lodging", "waterlogging", "drought", "frost"]] = Field(
        min_length=1, max_length=4
    )
    horizon_days: int = Field(default=7, ge=1, le=30, strict=True)

    @field_validator("hazard_types")
    @classmethod
    def unique_hazards(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("灾害类型不得重复")
        return values


def invoke(function, *args):
    try:
        return function(*args)
    except MarketCacheError as exc:
        raise HTTPException(
            503, detail={"code": "market_cache_invalid", "message": str(exc)}
        ) from exc


@router.get("/dashboard")
def dashboard(actor: Actor, project_id: ProjectId = "PRJ-001"):
    return invoke(decision.dashboard, project_id, actor)


@router.get("/futures")
def futures(
    actor: Actor,
    project_id: ProjectId = "PRJ-001",
    ticker: Annotated[str | None, Query(pattern=r"^c\d{4}$")] = None,
):
    return invoke(decision.futures, project_id, ticker, actor)


@router.get("/capabilities")
def capabilities(actor: Actor, project_id: ProjectId = "PRJ-001"):
    return decision.capabilities(project_id, actor)


@router.get("/policy-events")
def policy_events(actor: Actor, project_id: ProjectId = "PRJ-001"):
    return decision.policy_events(project_id, actor)


@router.post("/risk-assessments")
def risk_assessment(payload: RiskAssessmentRequest, actor: Actor):
    return decision.risk_assessment(payload.model_dump(mode="json"), actor)
