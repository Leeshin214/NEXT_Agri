from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "code": str(exc.status_code)},
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
):
    return JSONResponse(
        status_code=422,
        content={"error": "Validation failed", "detail": str(exc.errors())},
    )
