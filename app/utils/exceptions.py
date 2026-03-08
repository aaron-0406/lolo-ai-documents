"""
Custom exceptions for the AI Document service.
"""

from typing import Optional


class AIDocumentError(Exception):
    """Base exception for AI Document service."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        details: Optional[dict] = None,
    ):
        self.message = message
        self.code = code
        self.details = details or {}
        super().__init__(message)


class SessionNotFoundError(AIDocumentError):
    """Session does not exist."""

    def __init__(self, session_id: str):
        super().__init__(
            message=f"Session not found: {session_id}",
            code="SESSION_NOT_FOUND",
            details={"session_id": session_id},
        )


class SessionExpiredError(AIDocumentError):
    """Session has expired."""

    def __init__(self, session_id: str):
        super().__init__(
            message=f"Session has expired: {session_id}",
            code="SESSION_EXPIRED",
            details={"session_id": session_id},
        )


class CaseFileNotFoundError(AIDocumentError):
    """Case file does not exist."""

    def __init__(self, case_file_id: int):
        super().__init__(
            message=f"Case file not found: {case_file_id}",
            code="CASE_FILE_NOT_FOUND",
            details={"case_file_id": case_file_id},
        )


class InvalidDocumentTypeError(AIDocumentError):
    """Invalid or unsupported document type."""

    def __init__(self, document_type: str):
        super().__init__(
            message=f"Invalid document type: {document_type}",
            code="INVALID_DOCUMENT_TYPE",
            details={"document_type": document_type},
        )


class ClaudeAPIError(AIDocumentError):
    """Error from Claude API."""

    def __init__(self, message: str, original_error: Optional[Exception] = None):
        super().__init__(
            message=f"Claude API error: {message}",
            code="CLAUDE_API_ERROR",
            details={"original_error": str(original_error) if original_error else None},
        )


class TokenLimitExceededError(AIDocumentError):
    """Document exceeds token limit."""

    def __init__(self, tokens_used: int, max_tokens: int):
        super().__init__(
            message=f"Token limit exceeded: {tokens_used} > {max_tokens}",
            code="TOKEN_LIMIT_EXCEEDED",
            details={"tokens_used": tokens_used, "max_tokens": max_tokens},
        )


class RateLimitError(AIDocumentError):
    """Rate limit exceeded."""

    def __init__(self, limit: str, retry_after: Optional[int] = None):
        super().__init__(
            message=f"Rate limit exceeded: {limit}",
            code="RATE_LIMIT_EXCEEDED",
            details={"limit": limit, "retry_after": retry_after},
        )


class ValidationError(AIDocumentError):
    """Document validation failed."""

    def __init__(self, errors: list[str], warnings: Optional[list[str]] = None):
        super().__init__(
            message="Document validation failed",
            code="VALIDATION_ERROR",
            details={"errors": errors, "warnings": warnings or []},
        )
