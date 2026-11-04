import logging
from http import HTTPStatus

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppException(StarletteHTTPException):
    def __init__(
        self,
        message: str,
        error_code: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
    ):
        super().__init__(
            status_code=status_code,
            detail={
                "success": False,
                "message": message,
                "error_code": error_code,
            },
        )
        self.message = message
        self.error_code = error_code


def _error_response(
    message: str,
    error_code: str,
    status_code: int,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={
            "success": False,
            "message": message,
            "error_code": error_code,
        },
    )


async def app_exception_handler(
    _request: Request,
    exc: AppException,
) -> JSONResponse:
    return _error_response(
        message=exc.message,
        error_code=exc.error_code,
        status_code=exc.status_code,
    )


async def validation_exception_handler(
    _request: Request,
    _exc: RequestValidationError,
) -> JSONResponse:
    return _error_response(
        message="Request validation failed",
        error_code="VALIDATION_ERROR",
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


async def http_exception_handler(
    _request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    try:
        message = HTTPStatus(exc.status_code).phrase
    except ValueError:
        message = "HTTP request failed"

    return _error_response(
        message=message,
        error_code=f"HTTP_{exc.status_code}",
        status_code=exc.status_code,
        headers=exc.headers,
    )


async def unexpected_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    logger.error(
        "Unhandled exception while processing %s %s",
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return _error_response(
        message="An unexpected error occurred",
        error_code="INTERNAL_SERVER_ERROR",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
