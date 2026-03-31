"""FastAPI authentication dependencies."""

import os

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .storage import JsonStorage

security = HTTPBearer()

_storage: JsonStorage | None = None


def get_storage() -> JsonStorage:
    global _storage
    if _storage is None:
        _storage = JsonStorage()
    return _storage


def require_admin(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    admin_key = os.environ.get("RAROC_ADMIN_KEY", "")
    if not admin_key or credentials.credentials != admin_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin key",
        )
    return credentials.credentials


def require_api_key(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    storage: JsonStorage = Depends(get_storage),
) -> str:
    key = storage.validate_key(credentials.credentials)
    if not key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
        )
    storage.touch_key(key.key)
    return key.key
