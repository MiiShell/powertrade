import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.db import create_engine
from app.redis_conn import create_arq_redis
from app.routes import auth, chart, details, health, market, pine, stocks, system
from app.security import LoginThrottle, SessionStore, is_csrf_safe
from app.settings import Settings, get_settings

logging.getLogger("httpx").setLevel(logging.WARNING)  # never log request URLs
logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = create_engine(s)
        app.state.redis = create_arq_redis(s)
        app.state.sessions = SessionStore(
            app.state.redis, s.session_secret or "dev-only-insecure", s.session_max_age
        )
        app.state.throttle = LoginThrottle(app.state.redis, s.login_max_attempts, s.login_window_s)
        yield
        await app.state.redis.aclose()
        await app.state.engine.dispose()

    dev = s.env == "dev"
    app = FastAPI(
        title="PowerTrade API",
        lifespan=lifespan,
        docs_url="/api/docs" if dev else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if dev else None,
    )

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if not is_csrf_safe(
            request.method, request.headers.get("origin"), request.headers.get("sec-fetch-site"), s.origins
        ):
            return JSONResponse({"detail": "cross-site request blocked"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(system.router)
    app.include_router(market.router)
    app.include_router(chart.router)
    app.include_router(details.router)
    app.include_router(pine.router)
    app.include_router(stocks.router)
    return app


app = create_app()
