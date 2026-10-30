"""Authenticated, explicitly simulated V2 policy workspace API."""

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from app.platform.auth import login, require_user, revoke_session
from app.platform.business import BusinessError, execute_command, get_workspace, scenario

router = APIRouter(prefix="/api/v2", tags=["保单业务工作台"])


class SessionRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class WorkspaceCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=150)
    project_id: str = "PRJ-001"
    command: str = Field(min_length=1, max_length=80)
    target_id: str | None = None
    expected_version: int | None = Field(default=None, ge=1)
    payload: dict = Field(default_factory=dict)


class ScenarioRequest(BaseModel):
    project_id: str = "PRJ-001"
    settlement_price: float = Field(ge=0, le=100_000, allow_inf_nan=False)
    delay_days: int = Field(default=0, ge=0, le=365)


def invoke(function, *args):
    try:
        return function(*args)
    except BusinessError as exc:
        raise HTTPException(exc.status, detail={"code": exc.code, "message": exc.message}) from exc


@router.post("/session")
def create_session(request: SessionRequest):
    return login(request.username, request.password)


@router.get("/session")
def current_session(user: dict = Depends(require_user)):
    return {"user": user, "execution_mode": "simulation"}


@router.delete("/session", status_code=204)
def delete_session(authorization: str = Header(), user: dict = Depends(require_user)):
    revoke_session(authorization)
    return Response(status_code=204)


@router.get("/workspace")
def workspace(project_id: str = Query(default="PRJ-001"), user: dict = Depends(require_user)):
    return invoke(get_workspace, project_id, user)


@router.post("/workspace/commands")
def commands(request: WorkspaceCommand, user: dict = Depends(require_user)):
    return invoke(execute_command, request.model_dump(), user)


@router.post("/workspace/scenarios")
def scenarios(request: ScenarioRequest, user: dict = Depends(require_user)):
    return invoke(scenario, request.project_id, user, request.settlement_price, request.delay_days)


@router.get("/workspace/report")
def report(project_id: str = Query(default="PRJ-001"), user: dict = Depends(require_user)):
    if user["role"] == "customer":
        raise HTTPException(
            403, detail={"code": "forbidden", "message": "客户无权导出项目业务报告"}
        )
    data = invoke(get_workspace, project_id, user)
    import json

    data["report_type"] = "policy_operations_snapshot"
    data["report_notice"] = "项目业务档案，关联合同条款、交易确认和收付凭证"
    return Response(
        json.dumps(data, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="policy-workspace-report.json"'},
    )
