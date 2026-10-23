from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router
from app.core.config import get_settings
from app.api.comparison_routes import router as comparison_router
from app.api.analysis_routes import router as analysis_router
from app.api.price_routes import router as price_router

settings = get_settings()
app = FastAPI(
    title="玉米价格预测与农业保险风险分析",
    version="0.1.0",
    description="课程 Demo API；mock 数据明确标记。",
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
