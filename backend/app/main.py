from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router
from app.core.config import get_settings
from app.api.comparison_routes import router as comparison_router
from app.api.analysis_routes import router as analysis_router
from app.api.price_routes import router as price_router
from app.api.platform_routes import router as platform_router
from app.api.platform_research_routes import router as platform_research_router
from app.api.decision_routes import router as decision_router
from app.platform.store import database_url


@asynccontextmanager
async def lifespan(app: FastAPI):
    database_url()
    yield


settings = get_settings()
app = FastAPI(
    lifespan=lifespan,
    title="玉米保险业务平台",
    version="0.2.0",
    description="保单团队四模块工作台；数据、研究与业务办理共享项目及责任版本。",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


app.include_router(comparison_router)
app.include_router(analysis_router)
app.include_router(price_router)
app.include_router(platform_router)
app.include_router(platform_research_router)
app.include_router(decision_router)
