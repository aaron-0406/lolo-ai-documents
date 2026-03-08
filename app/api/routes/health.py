"""
Health check endpoint.
"""

from datetime import datetime

from fastapi import APIRouter, Request

from app.config import settings
from app.models.responses import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check(request: Request) -> HealthResponse:
    """
    Check health of all services.

    Returns status of:
    - MySQL connection (includes session storage)
    - Claude API availability
    """
    services = {}

    # Check MySQL (also used for session storage)
    try:
        mysql = request.app.state.mysql
        # Try to ensure connection and reconnect if needed
        await mysql.ensure_connection()
        if await mysql.check_connection():
            services["mysql"] = "ok"
        else:
            services["mysql"] = "error"
    except Exception as e:
        services["mysql"] = f"error: {str(e)[:50]}"

    # Check Claude API (just verify key is set)
    if settings.anthropic_api_key and settings.anthropic_api_key.startswith("sk-"):
        services["claude_api"] = "ok"
    else:
        services["claude_api"] = "not_configured"

    # Determine overall status
    all_ok = all(v == "ok" for v in services.values())
    status = "healthy" if all_ok else "degraded"

    return HealthResponse(
        status=status,
        version=settings.app_version,
        services=services,
        timestamp=datetime.utcnow().isoformat(),
    )
