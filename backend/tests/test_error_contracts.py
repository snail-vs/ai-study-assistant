import asyncio
import json
import unittest
from uuid import UUID
from unittest.mock import AsyncMock

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.ai.base import AIProviderError
from backend.main import (
    ai_provider_exception_handler,
    http_exception_handler,
    request_id_middleware,
    validation_exception_handler,
)


def request(*, request_id="request-123", method="GET", path="/api/v1/test", set_state=True):
    headers = [] if request_id is None else [(b"x-request-id", request_id.encode())]
    req = Request({
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers,
        "server": ("testserver", 80),
        "client": ("testclient", 1234),
        "root_path": "",
    })
    if set_state and request_id is not None:
        req.state.request_id = request_id
    return req


class ErrorResponseContractTests(unittest.TestCase):
    def test_not_found_uses_not_found_code_and_request_id(self):
        response = asyncio.run(http_exception_handler(
            request(), HTTPException(status_code=404, detail="Not found")
        ))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(json.loads(response.body), {
            "error": {
                "code": "NOT_FOUND",
                "message": "Not found",
                "details": {},
                "requestId": "request-123",
            },
        })

    def test_non_404_http_exception_uses_generic_http_error_code(self):
        response = asyncio.run(http_exception_handler(
            request(), HTTPException(status_code=409, detail="Conflict")
        ))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(json.loads(response.body), {
            "error": {
                "code": "HTTP_ERROR",
                "message": "Conflict",
                "details": {},
                "requestId": "request-123",
            },
        })

    def test_validation_error_exposes_errors_without_changing_envelope(self):
        exc = RequestValidationError([{
            "type": "missing",
            "loc": ("query", "limit"),
            "msg": "Field required",
            "input": None,
        }])

        response = asyncio.run(validation_exception_handler(request(), exc))

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.media_type, "application/json")
        self.assertEqual(response.body.decode(), (
            '{"error":{"code":"VALIDATION_ERROR","message":"请求参数校验失败",'
            '"details":{"errors":[{"type":"missing","loc":["query","limit"],'
            '"msg":"Field required","input":null}]},"requestId":"request-123"}}'
        ))

    def test_ai_provider_categories_map_to_safe_messages_and_preserve_details(self):
        messages = {
            "insufficient_balance": (
                "当前 Provider 余额不足，请更换模型或充值后重试。"
            ),
            "authentication": "当前 Provider API Key 无效或无权访问该模型。",
            "rate_limited": "当前 Provider 请求过于频繁，请稍后重试。",
            "schema_incompatible": (
                "当前模型不支持此结构化任务，请更换模型后重试。"
            ),
            "unsupported_protocol": (
                "当前模型使用的 API 协议暂未支持，请更换模型。"
            ),
            "unsupported_model": (
                "当前模型暂未识别，请检查模型名称或更换模型。"
            ),
            "provider_unavailable": "当前 AI Provider 暂时不可用，请稍后重试。",
        }
        for category, expected_message in messages.items():
            with self.subTest(category=category):
                exc = AIProviderError(
                    "raw provider reason",
                    category=category,
                    status_code=429,
                    provider_code="provider-code",
                )
                response = asyncio.run(ai_provider_exception_handler(request(), exc))
                payload = response.body.decode()

                self.assertEqual(response.status_code, 502)
                self.assertIn(f'"message":"{expected_message}"', payload)
                self.assertIn('"reason":"raw provider reason"', payload)
                self.assertIn(f'"category":"{category}"', payload)
                self.assertIn('"statusCode":429', payload)
                self.assertIn('"providerCode":"provider-code"', payload)
                self.assertIn('"requestId":"request-123"', payload)

    def test_unknown_ai_provider_category_uses_generic_safe_message(self):
        response = asyncio.run(ai_provider_exception_handler(
            request(), AIProviderError("raw", category="new_category")
        ))

        self.assertEqual(response.status_code, 502)
        self.assertIn('"message":"AI 服务调用失败"', response.body.decode())
        self.assertIn('"category":"new_category"', response.body.decode())

    def test_request_id_middleware_preserves_client_request_id_on_response(self):
        req = request(request_id="client-request-id", set_state=False)
        call_next = AsyncMock(return_value=JSONResponse({"ok": True}))

        response = asyncio.run(request_id_middleware(req, call_next))

        self.assertEqual(req.state.request_id, "client-request-id")
        self.assertEqual(response.headers["x-request-id"], "client-request-id")
        call_next.assert_awaited_once_with(req)

    def test_request_id_middleware_generates_uuid_when_header_is_missing(self):
        req = request(request_id=None, set_state=False)
        call_next = AsyncMock(return_value=JSONResponse({"ok": True}))

        response = asyncio.run(request_id_middleware(req, call_next))

        generated_id = response.headers["x-request-id"]
        self.assertEqual(req.state.request_id, generated_id)
        UUID(generated_id)


if __name__ == "__main__":
    unittest.main()
