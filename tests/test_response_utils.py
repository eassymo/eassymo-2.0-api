from fastapi import HTTPException, status

from app.utils.ResponseUtils import (
    error_json_response,
    error_status_code,
    get_unsuccessful_response,
)


def test_error_status_code_preserves_http_exception():
    exc = HTTPException(status_code=404, detail="Not found")
    assert error_status_code(exc) == 404


def test_error_status_code_defaults_to_500():
    assert error_status_code(Exception("boom")) == 500


def test_error_json_response_uses_correct_status():
    exc = HTTPException(status_code=422, detail="Validation failed")
    response = error_json_response(exc)
    assert response.status_code == 422
    assert response.body == b'{"error":"422: Validation failed"}'


def test_get_unsuccessful_response_shape():
    assert get_unsuccessful_response(ValueError("bad")) == {"error": "bad"}
