from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException, Path, Response
from app.core.config import get_settings
from app.repositories.comparison_repository import ComparisonError, ComparisonRepository
from app.services.comparison_service import ComparisonService, metadata

router = APIRouter(prefix="/api/v1/comparisons", tags=["comparisons"])
ID = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,80}$")]
Partition = Literal["validation", "test"]


def get_service():
    settings = get_settings()
    return ComparisonService(
        ComparisonRepository(settings.comparison_store_dir, settings.comparison_data_mode)
    )


Service = Annotated[ComparisonService, Depends(get_service)]


def invoke(call):
    try:
        return call()
    except ComparisonError as exc:
        raise HTTPException(exc.status, detail={"code": exc.code, "message": exc.message}) from exc


@router.get("/groups")
def groups(service: Service):
    return invoke(service.groups)


@router.get("/groups/{group_id}/runs")
def runs(group_id: ID, service: Service):
    return invoke(lambda: service.runs(group_id))


@router.get("/runs/{run_id}")
def detail(run_id: ID, service: Service, partition: Partition = "validation"):
    return invoke(lambda: metadata(service.bundle(run_id, partition)))


@router.get("/runs/{run_id}/metrics")
def metrics(run_id: ID, service: Service, partition: Partition = "validation"):
    return invoke(lambda: service.metrics(service.bundle(run_id, partition), partition))


@router.get("/runs/{run_id}/evidence")
def evidence(
    run_id: ID,
    service: Service,
    partition: Partition = "validation",
    view: Literal["calibration", "error_slices", "data_quality"] = "calibration",
):
    def read():
        bundle = service.bundle(run_id, partition)
        return {
            "run_id": run_id,
            "partition": partition,
            "view": view,
            "items": getattr(bundle.partitions[partition].evidence, view),
        }

    return invoke(read)


@router.get("/runs/{run_id}/cases")
def cases(
    run_id: ID, service: Service, partition: Partition = "validation", case_id: str | None = None
):
    def read():
        bundle = service.bundle(run_id, partition)
        rows = [
            case.model_dump()
            for case in bundle.partitions[partition].cases
            if case_id is None or case.case_id == case_id
        ]
        if case_id is not None and not rows:
            raise ComparisonError(404, "comparison_not_found", "未找到历史个案")
        return {"run_id": run_id, "partition": partition, "items": rows}

    return invoke(read)


@router.get("/runs/{run_id}/export")
def export(
    run_id: ID,
    service: Service,
    partition: Partition = "validation",
    format: Literal["json", "csv"] = "json",
):
    result = invoke(lambda: service.export(service.bundle(run_id, partition), partition, format))
    filename = f"{run_id}-{partition}.{format}"
    if format == "csv":
        return Response(
            result,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    from fastapi.responses import JSONResponse

    return JSONResponse(
        result, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )
