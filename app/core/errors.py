"""统一错误码和异常处理。

API、Service、Worker 和算法层应尽量抛出 AvatarError，避免只返回模糊的 failed。
"""

from enum import StrEnum

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ErrorCode(StrEnum):
    """业务错误码。"""

    INVALID_IMAGE_FORMAT = "INVALID_IMAGE_FORMAT"
    IMAGE_TOO_LARGE = "IMAGE_TOO_LARGE"
    IMAGE_RESOLUTION_TOO_HIGH = "IMAGE_RESOLUTION_TOO_HIGH"
    NO_FACE_DETECTED = "NO_FACE_DETECTED"
    MULTIPLE_FACES_DETECTED = "MULTIPLE_FACES_DETECTED"
    FACE_TOO_SMALL = "FACE_TOO_SMALL"
    FACE_OCCLUDED = "FACE_OCCLUDED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    MODEL_INFERENCE_FAILED = "MODEL_INFERENCE_FAILED"
    EXTERNAL_COMMAND_FAILED = "EXTERNAL_COMMAND_FAILED"
    PROCESSING_TIMEOUT = "PROCESSING_TIMEOUT"
    CUDA_OOM = "CUDA_OOM"
    QUEUE_LIMIT_EXCEEDED = "QUEUE_LIMIT_EXCEEDED"
    QUEUE_FULL = "QUEUE_FULL"
    QUEUE_UNAVAILABLE = "QUEUE_UNAVAILABLE"
    ACTIVE_JOB_EXISTS = "ACTIVE_JOB_EXISTS"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    NOT_FOUND = "NOT_FOUND"


class AvatarError(Exception):
    """项目业务异常。

    输入:
        code: 稳定错误码，供 Unity 前端做本地化提示。
        message: 面向调用方的错误说明。
        status_code: HTTP 状态码。

    输出:
        异常对象，由 FastAPI 或 Worker 统一捕获并写入任务状态。
    """

    def __init__(self, code: ErrorCode, message: str, status_code: int = 400) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器。

    输入:
        app: FastAPI 应用实例。

    输出:
        None。异常处理器会直接挂载到 app 上。
    """

    @app.exception_handler(AvatarError)
    async def handle_avatar_error(_: Request, exc: AvatarError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error_code": exc.code, "message": exc.message},
        )
