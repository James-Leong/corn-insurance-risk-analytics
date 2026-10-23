from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from app.core.config import get_settings
from app.domain.analysis import AnalysisRequest
from app.repositories.comparison_repository import ComparisonError
from app.services.analysis_service import AnalysisService

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])


def get_service():
    settings = get_settings()
    return AnalysisService(
        settings.market_cache_dir, settings.model_store_dir, settings.comparison_store_dir
    )


Service = Annotated[AnalysisService, Depends(get_service)]


def invoke(call):
    try:
        return call()
    except ComparisonError as exc:
        raise HTTPException(exc.status, detail={"code": exc.code, "message": exc.message}) from exc


@router.get("/options")
def options(service: Service):
    return invoke(service.options)


@router.post("/estimate")
def estimate(request: AnalysisRequest, service: Service):
    return invoke(lambda: service.estimate(request))
