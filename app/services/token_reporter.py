"""
Token Reporter Service - Reports token usage to the backend for analytics.

This service sends token usage data asynchronously to the lolo-backend
internal API after each AI operation completes.
"""

import httpx
from typing import Optional
from loguru import logger

from app.config import settings


class TokenReporter:
    """
    Reports token usage to the backend for analytics tracking.

    Supports two modes:
    1. Legacy: Single report after operation completes (report_tokens)
    2. Immediate: Init → Accumulate → Complete pattern for guaranteed tracking

    Uses fire-and-forget pattern with error logging to avoid blocking
    the main generation flow.
    """

    def __init__(self):
        self.backend_url = settings.backend_url
        self.internal_api_key = settings.internal_api_key
        self.base_url = f"{self.backend_url}/api/v1/judicial/ai-tokens/internal"
        self.endpoint = f"{self.base_url}/report"
        self.init_endpoint = f"{self.base_url}/init"
        self.accumulate_endpoint = f"{self.base_url}/accumulate"
        self.complete_endpoint = f"{self.base_url}/complete"
        self.enabled = bool(self.backend_url and self.internal_api_key)

        if not self.enabled:
            logger.warning("[TokenReporter] Disabled - missing BACKEND_URL or INTERNAL_API_KEY")

    async def report_tokens(
        self,
        session_id: str,
        judicial_case_file_id: int,
        document_type: str,
        operation_type: str,
        input_tokens: int,
        output_tokens: int,
        model_used: str,
        customer_id: int,
        customer_has_bank_id: int,
        created_by_customer_user_id: int,
        job_id: Optional[str] = None,
        document_name: Optional[str] = None,
    ) -> bool:
        """
        Report token usage to the backend asynchronously.

        Args:
            session_id: The AI document session ID
            judicial_case_file_id: The case file ID
            document_type: Type of document being generated
            operation_type: One of ANALYZE, GENERATE, REFINE, FINALIZE
            input_tokens: Number of input tokens used
            output_tokens: Number of output tokens used
            model_used: The Claude model used (e.g., claude-sonnet-4-6)
            customer_id: The customer (study) ID for multi-tenancy
            customer_has_bank_id: The CHB ID for multi-tenancy
            created_by_customer_user_id: The user who initiated the operation
            job_id: Optional job ID if this is a job-based operation
            document_name: Optional human-readable document name

        Returns:
            True if the report was sent successfully, False otherwise
        """
        if not self.enabled:
            logger.debug("[TokenReporter] Skipping report - disabled")
            return False

        payload = {
            "sessionId": session_id,
            "jobId": job_id,
            "judicialCaseFileId": judicial_case_file_id,
            "documentType": document_type,
            "documentName": document_name,
            "operationType": operation_type,
            "modelUsed": model_used,
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
            "customerId": customer_id,
            "customerHasBankId": customer_has_bank_id,
            "createdByCustomerUserId": created_by_customer_user_id,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self.endpoint,
                    json=payload,
                    headers={"X-Internal-API-Key": self.internal_api_key},
                )

                if response.status_code == 200:
                    result = response.json()
                    logger.debug(
                        f"[TokenReporter] Reported {input_tokens}+{output_tokens} tokens "
                        f"for {operation_type} on session {session_id}"
                    )
                    return True
                else:
                    logger.warning(
                        f"[TokenReporter] Failed to report tokens: "
                        f"HTTP {response.status_code} - {response.text}"
                    )
                    return False

        except httpx.TimeoutException:
            logger.warning(f"[TokenReporter] Timeout reporting tokens for session {session_id}")
            return False
        except httpx.RequestError as e:
            logger.warning(f"[TokenReporter] Request error: {e}")
            return False
        except Exception as e:
            logger.error(f"[TokenReporter] Unexpected error: {e}", exc_info=True)
            return False

    async def init_token_usage(
        self,
        session_id: str,
        judicial_case_file_id: int,
        document_type: str,
        operation_type: str,
        model_used: str,
        customer_id: int,
        customer_has_bank_id: int,
        created_by_customer_user_id: int,
        job_id: Optional[str] = None,
        document_name: Optional[str] = None,
    ) -> Optional[int]:
        """
        Initialize a token usage record with 0 tokens.
        Returns the recordId to use for accumulation, or None on failure.

        This should be called at the START of an operation (GENERATE, REFINE, etc.)
        before any Claude calls are made.
        """
        if not self.enabled:
            logger.debug("[TokenReporter] Skipping init - disabled")
            return None

        payload = {
            "sessionId": session_id,
            "jobId": job_id,
            "judicialCaseFileId": judicial_case_file_id,
            "documentType": document_type,
            "documentName": document_name,
            "operationType": operation_type,
            "modelUsed": model_used,
            "customerId": customer_id,
            "customerHasBankId": customer_has_bank_id,
            "createdByCustomerUserId": created_by_customer_user_id,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self.init_endpoint,
                    json=payload,
                    headers={"X-Internal-API-Key": self.internal_api_key},
                )

                if response.status_code == 200:
                    result = response.json()
                    record_id = result.get("recordId")
                    logger.info(
                        f"[TokenReporter] Initialized token record {record_id} "
                        f"for {operation_type} on session {session_id[:20]}..."
                    )
                    return record_id
                else:
                    logger.warning(
                        f"[TokenReporter] Failed to init token record: "
                        f"HTTP {response.status_code} - {response.text}"
                    )
                    return None

        except Exception as e:
            logger.error(f"[TokenReporter] Error initializing token record: {e}")
            return None

    async def accumulate_tokens(
        self,
        record_id: int,
        input_tokens: int,
        output_tokens: int,
    ) -> bool:
        """
        Accumulate tokens to an existing record.
        Should be called IMMEDIATELY after each successful Claude API call.

        Args:
            record_id: The ID returned from init_token_usage
            input_tokens: Number of input tokens from this Claude call
            output_tokens: Number of output tokens from this Claude call

        Returns:
            True if accumulation succeeded, False otherwise
        """
        if not self.enabled:
            return False

        if not record_id:
            logger.warning("[TokenReporter] Cannot accumulate - no record_id")
            return False

        payload = {
            "recordId": record_id,
            "inputTokens": input_tokens,
            "outputTokens": output_tokens,
        }

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    self.accumulate_endpoint,
                    json=payload,
                    headers={"X-Internal-API-Key": self.internal_api_key},
                )

                if response.status_code == 200:
                    logger.debug(
                        f"[TokenReporter] Accumulated {input_tokens}+{output_tokens} "
                        f"to record {record_id}"
                    )
                    return True
                else:
                    logger.warning(
                        f"[TokenReporter] Failed to accumulate tokens: "
                        f"HTTP {response.status_code}"
                    )
                    return False

        except Exception as e:
            logger.error(f"[TokenReporter] Error accumulating tokens: {e}")
            return False

    async def mark_operation_completed(
        self,
        record_id: int,
        success: bool,
    ) -> bool:
        """
        Mark an operation as completed (success or failure).
        This updates the operation_completed field and triggers daily metrics update.

        Args:
            record_id: The ID returned from init_token_usage
            success: True if operation completed successfully, False if it failed

        Returns:
            True if the update succeeded, False otherwise
        """
        if not self.enabled:
            return False

        if not record_id:
            logger.warning("[TokenReporter] Cannot mark complete - no record_id")
            return False

        payload = {
            "recordId": record_id,
            "success": success,
        }

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    self.complete_endpoint,
                    json=payload,
                    headers={"X-Internal-API-Key": self.internal_api_key},
                )

                if response.status_code == 200:
                    logger.info(
                        f"[TokenReporter] Marked record {record_id} as "
                        f"{'completed' if success else 'failed'}"
                    )
                    return True
                else:
                    logger.warning(
                        f"[TokenReporter] Failed to mark complete: "
                        f"HTTP {response.status_code}"
                    )
                    return False

        except Exception as e:
            logger.error(f"[TokenReporter] Error marking complete: {e}")
            return False


# Singleton instance
token_reporter = TokenReporter()


async def report_tokens_async(
    session_id: str,
    judicial_case_file_id: int,
    document_type: str,
    operation_type: str,
    input_tokens: int,
    output_tokens: int,
    model_used: str,
    customer_id: int,
    customer_has_bank_id: int,
    created_by_customer_user_id: int,
    job_id: Optional[str] = None,
    document_name: Optional[str] = None,
) -> bool:
    """
    Convenience function to report tokens using the global reporter.

    This function is designed to be used with FastAPI's BackgroundTasks:

    ```python
    background_tasks.add_task(
        report_tokens_async,
        session_id=session_id,
        judicial_case_file_id=case_id,
        document_type="demanda_ods",
        operation_type="GENERATE",
        input_tokens=token_usage.input_tokens,
        output_tokens=token_usage.output_tokens,
        model_used=token_usage.model,
        customer_id=customer_id,
        customer_has_bank_id=chb_id,
        created_by_customer_user_id=user_id,
    )
    ```
    """
    return await token_reporter.report_tokens(
        session_id=session_id,
        judicial_case_file_id=judicial_case_file_id,
        document_type=document_type,
        operation_type=operation_type,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model_used=model_used,
        customer_id=customer_id,
        customer_has_bank_id=customer_has_bank_id,
        created_by_customer_user_id=created_by_customer_user_id,
        job_id=job_id,
        document_name=document_name,
    )


async def init_token_usage_async(
    session_id: str,
    judicial_case_file_id: int,
    document_type: str,
    operation_type: str,
    model_used: str,
    customer_id: int,
    customer_has_bank_id: int,
    created_by_customer_user_id: int,
    job_id: Optional[str] = None,
    document_name: Optional[str] = None,
) -> Optional[int]:
    """
    Initialize a token usage record. Returns recordId for accumulation.

    Call this at the START of an operation before any Claude calls.
    """
    return await token_reporter.init_token_usage(
        session_id=session_id,
        judicial_case_file_id=judicial_case_file_id,
        document_type=document_type,
        operation_type=operation_type,
        model_used=model_used,
        customer_id=customer_id,
        customer_has_bank_id=customer_has_bank_id,
        created_by_customer_user_id=created_by_customer_user_id,
        job_id=job_id,
        document_name=document_name,
    )


async def accumulate_tokens_async(
    record_id: int,
    input_tokens: int,
    output_tokens: int,
) -> bool:
    """
    Accumulate tokens to an existing record.

    Call this IMMEDIATELY after each successful Claude API call.
    """
    return await token_reporter.accumulate_tokens(
        record_id=record_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


async def mark_operation_completed_async(
    record_id: int,
    success: bool,
) -> bool:
    """
    Mark operation as completed (success or failure).

    Call this at the END of the operation, whether it succeeded or failed.
    """
    return await token_reporter.mark_operation_completed(
        record_id=record_id,
        success=success,
    )
