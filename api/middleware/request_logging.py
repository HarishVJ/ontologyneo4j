"""Structured request/response logging middleware."""

import time
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from config.logging_config import get_logger

logger = get_logger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        elapsed = round((time.time() - start) * 1000, 1)
        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            elapsed_ms=elapsed,
        )
        return response
