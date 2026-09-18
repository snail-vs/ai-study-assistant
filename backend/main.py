import logging
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from .api import public_router, router
from .auth_api import router as auth_router
from .conversation_api import router as conversation_router
from .learning_space_api import router as learning_space_router
from .provider_api import router as provider_router
from .ai.base import AIProviderError
from .services.course_generation import resume_pending_course_generations
from . import models  # noqa: F401

app = FastAPI(title="StudyCenter API", version="0.1.0")


@app.on_event("startup")
async def resume_course_generations() -> None:
    await resume_pending_course_generations()
logger = logging.getLogger("studycenter.ai")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


def error_response(request: Request, code: str, message: str, details: dict | None = None, status_code: int = 500):
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "requestId": request.state.request_id,
            }
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
    return error_response(request, code, str(exc.detail), status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return error_response(request, "VALIDATION_ERROR", "请求参数校验失败", {"errors": exc.errors()}, 422)


@app.exception_handler(AIProviderError)
async def ai_provider_exception_handler(request: Request, exc: AIProviderError):
    logger.error(
        "AI provider request failed request_id=%s method=%s path=%s reason=%s",
        request.state.request_id,
        request.method,
        request.url.path,
        str(exc),
    )
    messages = {
        "insufficient_balance": "当前 Provider 余额不足，请更换模型或充值后重试。",
        "authentication": "当前 Provider API Key 无效或无权访问该模型。",
        "rate_limited": "当前 Provider 请求过于频繁，请稍后重试。",
        "schema_incompatible": "当前模型不支持此结构化任务，请更换模型后重试。",
        "unsupported_protocol": "当前模型使用的 API 协议暂未支持，请更换模型。",
        "unsupported_model": "当前模型暂未识别，请检查模型名称或更换模型。",
        "provider_unavailable": "当前 AI Provider 暂时不可用，请稍后重试。",
    }
    details = {
        "reason": str(exc),
        "category": exc.category,
        "statusCode": exc.status_code,
        "providerCode": exc.provider_code,
    }
    return error_response(request, "AI_PROVIDER_ERROR", messages.get(exc.category, "AI 服务调用失败"), details, 502)

app.include_router(public_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(provider_router, prefix="/api/v1")
app.include_router(learning_space_router, prefix="/api/v1")
app.include_router(conversation_router, prefix="/api/v1")
app.include_router(router, prefix="/api/v1")
