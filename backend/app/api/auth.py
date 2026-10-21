"""Password login (docs/api.md#authentication).

`POST /login` exchanges the app password (app/system/app_password.py:
APP_PASSWORD until changed with `POST /password`) for a signed token valid
for TOKEN_TTL. The signing key is derived from the password (its hash once
changed), so changing it invalidates every token. The dashboard server keeps
the token in an HTTP-only cookie and sends it as `Authorization: Bearer <token>`.

Failed logins are rate-limited per client IP in Redis. The dashboard calls
the API server-side, so it forwards the visitor's IP in X-Forwarded-For.
"""

import base64
import hashlib
import hmac
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.system.app_password import MIN_LENGTH, password_matches, save_password, secret
from app.watchdog.redis_client import get_redis

TOKEN_TTL_SECONDS = 7 * 24 * 3600
MAX_FAILED_LOGINS = 5
FAILED_LOGIN_WINDOW_SECONDS = 15 * 60
_FAILED_KEY = "login:failed:{}"
# A logged-out token, by its signature - kept until the token would expire.
_REVOKED_KEY = "login:revoked:{}"

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)


def _signing_key(password: str) -> bytes:
    return hashlib.sha256(b"trading-app-session:" + password.encode()).digest()


def _signature(expires_at: int, password: str) -> str:
    mac = hmac.new(_signing_key(password), str(expires_at).encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def issue_token(password: str, now: float) -> str:
    expires_at = int(now) + TOKEN_TTL_SECONDS
    return f"{expires_at}.{_signature(expires_at, password)}"


def token_valid(token: str, password: str, now: float) -> bool:
    expires_str, _, signature = token.partition(".")
    if not password or not expires_str.isdigit():
        return False
    expires_at = int(expires_str)
    return expires_at > now and hmac.compare_digest(signature, _signature(expires_at, password))


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _revoked_key(token: str) -> str:
    return _REVOKED_KEY.format(token.partition(".")[2])


async def require_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    if credentials is None or not token_valid(credentials.credentials, await secret(), time.time()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not logged in")
    if await get_redis().exists(_revoked_key(credentials.credentials)):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="logged out")


class LoginRequest(BaseModel):
    password: str


class LoginResult(BaseModel):
    token: str
    expires_in: int


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=MIN_LENGTH)


async def _check_password(password: str, request: Request) -> None:
    """Raises unless `password` is the app password; failures are counted
    per client IP and lock it out for a while."""
    redis = get_redis()
    key = _FAILED_KEY.format(client_ip(request))
    failed = int(await redis.get(key) or 0)
    if failed >= MAX_FAILED_LOGINS:
        raise HTTPException(status_code=429, detail="too many failed logins, try again later")
    if not await password_matches(password):
        await redis.incr(key)
        await redis.expire(key, FAILED_LOGIN_WINDOW_SECONDS, nx=True)
        raise HTTPException(status_code=401, detail="wrong password")
    await redis.delete(key)


def _token(signed_with: str) -> LoginResult:
    return LoginResult(token=issue_token(signed_with, time.time()), expires_in=TOKEN_TTL_SECONDS)


@router.post("/login", response_model=LoginResult)
async def login(payload: LoginRequest, request: Request) -> LoginResult:
    if not await secret():
        raise HTTPException(status_code=503, detail="APP_PASSWORD is not set")
    await _check_password(payload.password, request)
    return _token(await secret())


@router.post("/logout", status_code=204, dependencies=[Depends(require_auth)])
async def logout(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    """Revokes the caller's token until it would have expired - a copy of it
    stops working too, not only the cookie."""
    assert credentials is not None  # require_auth
    token = credentials.credentials
    ttl = int(token.partition(".")[0]) - int(time.time())
    if ttl > 0:
        await get_redis().set(_revoked_key(token), 1, ex=ttl)


@router.post("/password", response_model=LoginResult, dependencies=[Depends(require_auth)])
async def change_password(payload: PasswordChange, request: Request) -> LoginResult:
    """Replaces the app password (the current one required): every token is
    logged out - the caller gets a new one."""
    await _check_password(payload.current_password, request)
    await save_password(payload.new_password)
    return _token(await secret())
