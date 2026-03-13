"""
LOLO AI Documents Microservice - Main Application

FastAPI application for generating legal documents using AI multi-agent system.

NOTE: Session management is handled by lolo-backend (MySQL).
This microservice uses the same MySQL database for reading/updating sessions.
Redis has been removed - all session data is stored in JUDICIAL_AI_DOCUMENT_SESSION table.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.config import settings
from app.api.routes import analyze, generate, refine, finalize, document_types, health, annexes, learning
from app.services.mysql_service import MySQLService
from app.services.s3_service import S3Service
from app.services.document_context_service import DocumentContextService
from app.utils.llm_worker import llm_worker


# Rate limiter
limiter = Limiter(key_func=get_remote_address)

# Background task handle
_keepalive_task = None


async def mysql_keepalive(mysql_service: MySQLService, interval: int = 60):
    """
    Background task that pings MySQL every `interval` seconds
    to keep connections alive and prevent timeout disconnections.
    """
    while True:
        try:
            await asyncio.sleep(interval)
            await mysql_service.ensure_connection()
            logger.debug("MySQL keepalive ping successful")
        except asyncio.CancelledError:
            logger.info("MySQL keepalive task cancelled")
            break
        except Exception as e:
            logger.warning(f"MySQL keepalive ping failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Application lifespan events."""
    global _keepalive_task

    # Startup
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"Environment: {settings.environment}")

    # Initialize MySQL service (sessions are stored in MySQL, not Redis)
    app.state.mysql = MySQLService()
    await app.state.mysql.connect()
    logger.info("MySQL connected successfully")

    # Start MySQL keepalive background task (ping every 60 seconds)
    # This is very lightweight (just SELECT 1) and prevents RDS from closing idle connections
    _keepalive_task = asyncio.create_task(mysql_keepalive(app.state.mysql, interval=60))
    logger.info("MySQL keepalive task started (60s interval)")

    # Initialize S3 service for document extraction
    app.state.s3 = S3Service()
    logger.info("S3 service initialized")

    # Initialize Document Context service (coordinates MySQL + S3 + PDF extraction)
    app.state.document_context = DocumentContextService(
        mysql_service=app.state.mysql,
        s3_service=app.state.s3,
    )
    logger.info("Document context service initialized")

    # LLM Worker will auto-start on first request, but we log the config
    logger.info(
        f"LLM Worker configured - Sonnet: {settings.sonnet_output_tpm} output TPM, "
        f"Haiku: {settings.haiku_output_tpm} output TPM"
    )

    yield

    # Shutdown
    logger.info("Shutting down services...")

    # Stop LLM worker
    llm_worker.stop()

    # Cancel keepalive task
    if _keepalive_task:
        _keepalive_task.cancel()
        try:
            await _keepalive_task
        except asyncio.CancelledError:
            pass

    await app.state.mysql.disconnect()
    logger.info("Shutdown complete")


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    description="AI Document Generation Microservice for LOLO Legal Platform",
    version=settings.app_version,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan,
)

# Add rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
)


# Include routers
app.include_router(health.router, tags=["Health"])
app.include_router(document_types.router, prefix="/api/v1/documents", tags=["Document Types"])
app.include_router(analyze.router, prefix="/api/v1/documents", tags=["Analyze"])
app.include_router(generate.router, prefix="/api/v1/documents", tags=["Generate"])
app.include_router(refine.router, prefix="/api/v1/documents", tags=["Refine"])
app.include_router(finalize.router, prefix="/api/v1/documents", tags=["Finalize"])
app.include_router(annexes.router, prefix="/api/v1/documents/annexes", tags=["Annexes"])
app.include_router(learning.router, prefix="/internal/learning", tags=["Learning (Internal)"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": settings.app_name,
        "version": settings.app_version,
        "status": "running",
        "docs": "/docs" if settings.debug else "disabled",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
