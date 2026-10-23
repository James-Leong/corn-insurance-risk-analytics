from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.core.config import get_settings
from app.services.price_service import PriceError, overview

router = APIRouter(prefix="/api/v1/prices", tags=["prices"])


@router.get("/overview")
def price_overview(ticker: Annotated[str, Query(pattern=r"^c\d{4}$")] = "c2701"):
    try:
        return overview(get_settings().price_store_dir, ticker)
    except PriceError as exc:
        raise HTTPException(exc.status, detail={"message": exc.message}) from exc
