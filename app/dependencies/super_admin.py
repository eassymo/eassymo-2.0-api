from fastapi import HTTPException, Request, status


def require_super_admin(request: Request) -> dict:
    """
    FastAPI dependency that requires the Firebase custom claim super_admin=true.
    """
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not authenticated",
        )

    if user.get("super_admin") is not True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required",
        )

    return user
