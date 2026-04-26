"""FastAPI application entry point for CodeSentry."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    settings = get_settings()
    logger.info(
        "CodeSentry starting | provider=%s model=%s workspace=%s",
        settings.model_provider.value,
        settings.model_name,
        settings.workspace_root,
    )
    # TODO: Phase 2+ — init DB, load tools, warm prompt cache
    yield
    logger.info("CodeSentry shutting down")


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="CodeSentry",
        description="AI Coding Agent — analyze, plan, and modify code repositories",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health check
    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "version": "0.1.0",
            "provider": settings.model_provider.value,
            "model": settings.model_name,
        }

    # API routes
    from app.api.routes import router as api_router
    app.include_router(api_router)

    return app


# Application instance for uvicorn
app = create_app()
