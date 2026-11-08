from typing import Annotated

from arq.connections import ArqRedis
from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncEngine

from app.security import SESSION_COOKIE, SessionStore


def get_engine(request: Request) -> AsyncEngine:
    engine: AsyncEngine = request.app.state.engine
    return engine


def get_redis(request: Request) -> ArqRedis:
    redis: ArqRedis = request.app.state.redis
    return redis


def get_sessions(request: Request) -> SessionStore:
    store: SessionStore = request.app.state.sessions
    return store


async def require_user(
    sessions: Annotated[SessionStore, Depends(get_sessions)],
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> str:
    user = await sessions.load(token)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    return user


CurrentUser = Annotated[str, Depends(require_user)]
