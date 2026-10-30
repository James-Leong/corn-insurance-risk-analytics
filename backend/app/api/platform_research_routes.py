"""Business-scoped data and immutable research API."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.platform.auth import require_user
from app.platform import data, research
from app.repositories.market_cache import MarketCacheError

router = APIRouter(prefix="/api/v2", tags=["platform-research"])
Actor = Annotated[dict, Depends(require_user)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DataQuery(StrictModel):
    series_id: str = Field(min_length=1, max_length=150)
    start_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    as_of: str | None = Field(default=None, max_length=40)
    availability_mode: Literal["source_published", "platform_available"] = "source_published"


class DatasetInput(DataQuery):
    name: str = Field(min_length=1, max_length=120)
    as_of: str = Field(min_length=10, max_length=40)
    project_id: str | None = Field(default=None, max_length=80)


class FactorInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    project_id: str | None = Field(default=None, max_length=80)
    operator: Literal[
        "lag", "return", "rolling_mean", "volatility", "ratio", "diff", "expression"
    ] = "expression"
    expression: str | None = Field(default=None, max_length=300)
    input_field: str = Field(default="value", pattern=r"^[a-z_][a-z_0-9]*$")
    denominator_field: str = Field(default="value", pattern=r"^[a-z_][a-z_0-9]*$")
    window: int = Field(default=5, ge=1, le=120)
    lag: int = Field(default=1, ge=1, le=120)


class RunInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    project_id: str | None = Field(default=None, max_length=80)
    dataset_id: str = Field(min_length=1, max_length=80)
    factor_ids: list[str] = Field(default_factory=list, max_length=6)
    model_id: Literal["naive_last", "moving_average", "linear_trend", "factor_ridge"] = "naive_last"
    parameters: dict = Field(default_factory=dict)
    target: Literal["price", "payout"] = "price"
    train_end: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    validation_end: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    test_end: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    policy_terms: dict | None = None


class ReportInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    run_id: str = Field(min_length=1, max_length=80)
    conclusion: str = Field(min_length=1, max_length=5000)
    share_scope: Literal["private", "team"] = "private"
    project_id: str | None = Field(default=None, max_length=80)


class ImportInput(StrictModel):
    mode: Literal["preview", "confirm"] = "preview"
    source_id: str = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=120)
    source_uri: str = Field(min_length=8, max_length=1000)
    source_published_at: str = Field(min_length=10, max_length=40)
    source_revision: str = Field(min_length=1, max_length=80)
    kind: Literal["trade", "supply_demand"]
    period_type: Literal["calendar_month", "calendar_year", "MY", "TY"]
    unit: Literal["吨", "千吨", "万吨", "kg", "USD", "CNY"]
    rows: list[dict] = Field(default_factory=list, max_length=5000)
    csv_content: str | None = Field(default=None, max_length=2_000_000)
    is_fixture: bool = False


def invoke(fn, *args):
    try:
        return fn(*args)
    except MarketCacheError as exc:
        raise HTTPException(
            503, detail={"code": "market_cache_invalid", "message": str(exc)}
        ) from exc
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise HTTPException(422, detail={"code": "research_invalid", "message": str(exc)}) from exc


@router.get("/data/catalog")
def get_catalog(actor: Actor):
    research.internal(actor)
    return {**invoke(data.catalog), "models": research.MODELS, "operators": research.OPERATORS}


@router.post("/data/query")
def query(payload: DataQuery, actor: Actor):
    research.internal(actor)
    return invoke(data.query_data, payload.model_dump(exclude_none=True))


@router.post("/data/imports", status_code=201)
def import_data(payload: ImportInput, actor: Actor):
    return invoke(research.import_data, payload.model_dump(exclude_none=True), actor)


@router.get("/research/datasets")
def datasets(actor: Actor):
    return research.list_objects("dataset", actor)


@router.post("/research/datasets", status_code=201)
def save_dataset(payload: DatasetInput, actor: Actor):
    return invoke(research.save_dataset, payload.model_dump(exclude_none=True), actor)


@router.get("/research/datasets/{item_id}")
def dataset(item_id: str, actor: Actor):
    return research.get_object("dataset", item_id, actor)


@router.get("/research/factors")
def factors(actor: Actor):
    return research.list_objects("factor", actor)


@router.post("/research/factors", status_code=201)
def save_factor(payload: FactorInput, actor: Actor):
    return invoke(research.save_factor, payload.model_dump(exclude_none=True), actor)


@router.get("/research/runs")
def runs(actor: Actor):
    return research.list_objects("run", actor)


@router.post("/research/runs", status_code=201)
def run(payload: RunInput, actor: Actor):
    return invoke(research.run_experiment, payload.model_dump(exclude_none=True), actor)


@router.get("/research/runs/{item_id}")
def run_detail(item_id: str, actor: Actor):
    return research.get_object("run", item_id, actor)


@router.get("/research/reports")
def reports(actor: Actor):
    return research.list_objects("report", actor)


@router.post("/research/reports", status_code=201)
def save_report(payload: ReportInput, actor: Actor):
    return invoke(research.save_report, payload.model_dump(exclude_none=True), actor)


@router.get("/research/reports/{item_id}")
def report(item_id: str, actor: Actor):
    return research.get_report(item_id, actor)
