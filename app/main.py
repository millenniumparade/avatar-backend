"""FastAPI 应用入口。

本文件只负责创建 API 服务、注册路由和挂载全局异常处理器。
耗时算法不应在这里执行，应交给 worker 层异步处理。
"""

from fastapi import FastAPI

from app.api.v1.avatar_jobs import router as avatar_jobs_router
from app.api.v1.avatar_results import router as avatar_results_router
from app.api.v1.users import router as users_router
from app.core.config import settings
from app.core.errors import register_exception_handlers


def create_app() -> FastAPI:
    """创建 FastAPI 实例。

    输入:
        无。

    输出:
        FastAPI: 已完成路由和异常处理注册的应用实例。
    """
    app = FastAPI(
        title=settings.project_name,
        version=settings.api_version,
        description="面向 Unity 的 AI 卡通人脸生成后端服务。",
    )

    app.include_router(avatar_jobs_router, prefix="/api/v1/avatar/jobs", tags=["avatar-jobs"])
    app.include_router(avatar_results_router, prefix="/api/v1/avatar/results", tags=["avatar-results"])
    app.include_router(users_router, prefix="/api/v1/users", tags=["users"])
    register_exception_handlers(app)
    return app


app = create_app()

