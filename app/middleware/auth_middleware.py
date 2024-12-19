from fastapi import Request, HTTPException
from firebase_admin import auth
from typing import Optional
from functools import wraps


async def verify_token(request: Request) -> Optional[dict]:
    headers = request.headers
    if not headers.get("Authorization"):
        raise HTTPException(status_code=401, detail="No Auth token provided")

    try:
        token = headers.get("Authorization").replace("Bearer ", "")
        decoded_token = auth.verify_id_token(token)
        request.state.user = decoded_token
        return decoded_token
    except Exception as e:
        raise HTTPException(
            status_code=401, detail=f'Invalid authentication token {e}')


def require_auth(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        request = kwargs.get("request")
        if not request:
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

        if not request:
            raise HTTPException(
                status_code=500, detail="Request object not found")

        decoded_token = await verify_token(request)
        request.state.user = decoded_token
        return await func(*args, **kwargs)

    return wrapper