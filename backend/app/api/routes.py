from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from app.services.demo_service import DemoService
from app.repositories.market_cache import MarketCacheError

router = APIRouter(prefix="/api/v1")
service = DemoService()


class ScenarioRequest(BaseModel):
    insured_tons: float = Field(ge=0, le=1_000_000)
    guarantee_price: float = Field(ge=0, le=100_000)
    settlement_price: float = Field(ge=0, le=100_000)
    deductible_per_ton: float = Field(default=0, ge=0)
    payout_cap: float | None = Field(default=None, ge=0)


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "corn-insurance-risk-demo"}


@router.get("/dashboard")
def dashboard() -> dict:
    try:
        return service.dashboard()
    except MarketCacheError as exc:
        raise HTTPException(
            status_code=503, detail={"code": "market_cache_invalid", "message": str(exc)}
        ) from exc


@router.get("/market/corn")
def market(days: int = Query(default=90, ge=30, le=365)) -> dict:
    try:
        return service.market.get_corn_series(days)
    except MarketCacheError as exc:
        raise HTTPException(
            status_code=503, detail={"code": "market_cache_invalid", "message": str(exc)}
        ) from exc


@router.post("/insurance/scenario")
def scenario(request: ScenarioRequest) -> dict:
    try:
        return service.scenario(**request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
