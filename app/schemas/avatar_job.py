"""头像任务 API schema。"""

from pydantic import BaseModel, Field


class AvatarJobCreateResponse(BaseModel):
    """创建任务响应。

    输出给 Unity:
        job_id: 后续轮询任务状态使用。
        status: 初始状态，通常为 queued。
        estimated_wait_seconds: 粗略等待时间，用于前端 UI 提示。
    """

    job_id: str
    status: str = "queued"
    estimated_wait_seconds: int = 8


class AvatarJobStatusResponse(BaseModel):
    """任务状态响应。

    输出给 Unity:
        processing 时返回 progress/current_stage。
        succeeded 时返回 result_id。
        failed 时返回 error_code/message。
    """

    job_id: str
    status: str
    progress: int = Field(ge=0, le=100)
    stage: str | None = None
    result_id: str | None = None
    error_code: str | None = None
    message: str | None = None

