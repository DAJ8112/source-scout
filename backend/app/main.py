from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.profile_routes import router as profile_router
from app.api.routes import router
from app.config import settings
from app.connectors.http import SafeHttpClient
from app.db import SessionLocal
from app.services.matching import HybridMatcher


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.session_factory = SessionLocal
    app.state.http = SafeHttpClient()
    app.state.matcher = HybridMatcher(settings)
    yield
    await app.state.http.close()
    await app.state.matcher.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Referral Job Monitor Connector Lab",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    app.include_router(profile_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
