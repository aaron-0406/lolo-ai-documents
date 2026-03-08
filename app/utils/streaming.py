"""
SSE (Server-Sent Events) streaming utilities.
"""

import json
from typing import Any


def create_sse_message(event: str, data: dict[str, Any]) -> str:
    """
    Create a properly formatted SSE message.

    Args:
        event: Event type (token, draft_update, done, error)
        data: Event data as dictionary

    Returns:
        Formatted SSE message string
    """
    json_data = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {json_data}\n\n"


def create_sse_comment(comment: str) -> str:
    """
    Create an SSE comment (for keepalive).

    Args:
        comment: Comment text

    Returns:
        Formatted SSE comment string
    """
    return f": {comment}\n\n"


def create_sse_keepalive() -> str:
    """Create a keepalive SSE comment."""
    return create_sse_comment("keepalive")


# Event type constants
SSE_EVENT_TOKEN = "token"
SSE_EVENT_DRAFT_UPDATE = "draft_update"
SSE_EVENT_DONE = "done"
SSE_EVENT_ERROR = "error"
SSE_EVENT_PROCESSING = "processing"
