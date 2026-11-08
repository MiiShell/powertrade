from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.deps import CurrentUser, get_sessions
from app.security import SESSION_COOKIE, LoginThrottle, SessionStore, check_credentials
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)
    totp: str | None = Field(default=None, pattern=r"^\d{6}$")


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    sessions: Annotated[SessionStore, Depends(get_sessions)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    throttle: LoginThrottle = request.app.state.throttle
    ip = _client_ip(request)
    if await throttle.blocked(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many attempts")
    ok = check_credentials(
        expected_user=settings.admin_user,
        password_hash=settings.admin_password_hash,
        totp_secret=settings.admin_totp_secret,
        user=body.username,
        password=body.password,
        totp=body.totp,
    )
    if not ok:
        await throttle.fail(ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    await throttle.reset(ip)
    token = await sessions.create(body.username)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    sessions: Annotated[SessionStore, Depends(get_sessions)],
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    await sessions.destroy(token)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me")
async def me(user: CurrentUser) -> dict[str, str]:
    return {"user": user}
