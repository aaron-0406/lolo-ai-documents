"""
LLM Utilities - Helper functions for LLM operations.

Note: For rate-limited API calls, use llm_worker.submit_to_worker() instead.
This module provides utilities for streaming and direct LLM access.
"""

import asyncio
from typing import Any, List, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage
from loguru import logger

from app.config import settings


# Retry settings for transient errors (NOT rate limits - worker handles those)
MAX_RETRIES = 2
OVERLOAD_RETRY_DELAY = 30  # seconds


def create_llm(
    model: Optional[str] = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    streaming: bool = False,
) -> ChatAnthropic:
    """
    Create a ChatAnthropic instance with default settings.

    Use this for streaming operations. For regular calls, prefer
    llm_worker.submit_to_worker() which handles rate limiting.

    Args:
        model: Model name, defaults to settings.claude_model
        max_tokens: Maximum output tokens
        temperature: Temperature for generation
        streaming: Enable streaming mode

    Returns:
        Configured ChatAnthropic instance
    """
    return ChatAnthropic(
        model=model or settings.claude_model,
        api_key=settings.anthropic_api_key,
        max_tokens=max_tokens,
        temperature=temperature,
        streaming=streaming,
    )


def is_overload_error(error: Exception) -> bool:
    """Check if an error is an API overload error (529)."""
    error_str = str(error).lower()
    return "overloaded" in error_str or "529" in error_str


def is_transient_error(error: Exception) -> bool:
    """Check if an error is transient and worth retrying."""
    error_str = str(error).lower()
    return (
        is_overload_error(error) or
        "connection" in error_str or
        "timeout" in error_str or
        "temporary" in error_str
    )


async def invoke_with_retry(
    llm: ChatAnthropic,
    messages: List[BaseMessage],
    max_retries: int = MAX_RETRIES,
) -> Any:
    """
    Invoke LLM with retry on transient errors (overload, connection issues).

    Note: This does NOT handle rate limits (429). For rate-limited calls,
    use llm_worker.submit_to_worker() instead.

    Args:
        llm: The ChatAnthropic instance
        messages: List of messages to send
        max_retries: Maximum number of retry attempts

    Returns:
        LLM response

    Raises:
        Exception: If all retries are exhausted or non-retryable error
    """
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            response = await llm.ainvoke(messages)
            return response

        except Exception as e:
            last_error = e

            # Only retry transient errors
            if is_transient_error(e) and attempt < max_retries:
                delay = min(OVERLOAD_RETRY_DELAY * (2 ** attempt), 120)

                logger.warning(
                    f"[LLM] Transient error, waiting {delay}s before retry "
                    f"(attempt {attempt + 1}/{max_retries + 1}): {e}"
                )

                await asyncio.sleep(delay)
                continue

            # For other errors (including rate limits), don't retry
            logger.error(f"[LLM] Error (not retrying): {e}")
            raise

    # All retries exhausted
    logger.error(f"[LLM] All {max_retries + 1} attempts exhausted")
    raise last_error
