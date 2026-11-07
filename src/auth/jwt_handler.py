"""JWT Auth Handler"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
from fastapi import Request, HTTPException, status
from src.config import get_settings

settings = get_settings()


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload
    except JWTError:
        return None


def get_current_user_from_request(request: Request) -> Optional[dict]:
    token = request.cookies.get("access_token")
    if not token:
        return None
    return decode_token(token)


def require_user(request: Request) -> dict:
    user = get_current_user_from_request(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/auth/login"}
        )
    return user


def require_manager(request: Request) -> dict:
    user = require_user(request)
    if user.get("role") != "manager":
        raise HTTPException(status_code=403, detail="Manager access required")
    return user


def require_developer(request: Request) -> dict:
    user = require_user(request)
    if user.get("role") != "developer":
        raise HTTPException(status_code=403, detail="Developer access required")
    return user
