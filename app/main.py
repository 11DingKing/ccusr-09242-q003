from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import Base, engine
from .routers import entities, parks, projects, workflow, statistics, capacity
from .migrations import ensure_capacity_revision_schema

Base.metadata.create_all(bind=engine)
ensure_capacity_revision_schema()

app = FastAPI(
    title=settings.PROJECT_NAME,
    description=(
        "水果深加工招商台账后端服务。\n\n"
        "覆盖东盟方与广西方合作主体、产业园区、深加工合作项目、"
        "合作意向与多轮洽谈、立项审批、里程碑进度跟踪，以及园区/品类维度的统计分析。\n\n"
        "项目状态：招商中 → 洽谈中 → 已立项 → 建设中 → 已投产\n"
        "投资金额单位：万元；产能单位：吨/年；土地单位：亩"
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["系统"], summary="健康检查")
def root():
    return {
        "service": settings.PROJECT_NAME,
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "api_prefix": settings.API_V1_PREFIX,
    }


prefix = settings.API_V1_PREFIX
app.include_router(entities.router, prefix=prefix)
app.include_router(parks.router, prefix=prefix)
app.include_router(projects.router, prefix=prefix)
app.include_router(workflow.router, prefix=prefix)
app.include_router(statistics.router, prefix=prefix)
app.include_router(capacity.router, prefix=prefix)
