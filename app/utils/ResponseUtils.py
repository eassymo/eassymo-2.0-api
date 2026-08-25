from fastapi import HTTPException, status
from fastapi.responses import JSONResponse


def get_successful_response(body):
    return {
        "body": body
    }


def get_unsuccessful_response(exception: Exception):
    return {
        "error": str(exception)
    }


def error_status_code(exception: Exception) -> int:
    """Resolve the HTTP status code for an exception, preserving HTTPException codes."""
    if isinstance(exception, HTTPException):
        return exception.status_code
    return status.HTTP_500_INTERNAL_SERVER_ERROR


def error_json_response(exception: Exception) -> JSONResponse:
    """Return a JSONResponse with the correct HTTP status code for the given exception."""
    return JSONResponse(
        status_code=error_status_code(exception),
        content=get_unsuccessful_response(exception),
    )
