"""
LLM Worker - Centralized queue for API calls with rate limit management.

Serializes all LLM API calls and ensures we stay within Anthropic rate limits.
Tracks usage per model (requests, input tokens, output tokens) within 60-second windows.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage
from loguru import logger

from app.config import settings


@dataclass
class ModelLimits:
    """Rate limits for a specific model."""
    rpm: int  # Requests per minute
    input_tpm: int  # Input tokens per minute
    output_tpm: int  # Output tokens per minute


@dataclass
class ModelUsage:
    """Tracks usage for a model within a time window."""
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    window_start: float = field(default_factory=time.time)


@dataclass
class TokenUsage:
    """Token usage from an LLM response."""
    input_tokens: int
    output_tokens: int
    model: str


@dataclass
class LLMResponse:
    """Response from LLM including the message and token usage."""
    message: Any  # The AIMessage from the LLM
    token_usage: TokenUsage


@dataclass
class LLMRequest:
    """A request waiting in the queue."""
    model: str
    messages: List[BaseMessage]
    max_tokens: int
    temperature: float
    estimated_input_tokens: int
    estimated_output_tokens: int
    future: Optional[asyncio.Future] = None  # Set in submit() within async context


class LLMWorker:
    """
    Centralized worker that manages all LLM API calls.

    Features:
    - Single queue for all requests
    - Per-model usage tracking
    - Automatic waiting when limits are reached
    - Configurable limits via environment variables
    """

    WINDOW_SECONDS = 60  # Rate limit window

    def __init__(self):
        # Model limits from config (can be overridden via ENV)
        self.limits: dict[str, ModelLimits] = {
            settings.claude_model: ModelLimits(
                rpm=settings.sonnet_rpm,
                input_tpm=settings.sonnet_input_tpm,
                output_tpm=settings.sonnet_output_tpm,
            ),
            settings.claude_model_fast: ModelLimits(
                rpm=settings.haiku_rpm,
                input_tpm=settings.haiku_input_tpm,
                output_tpm=settings.haiku_output_tpm,
            ),
        }

        # Usage tracking per model
        self.usage: dict[str, ModelUsage] = {
            settings.claude_model: ModelUsage(),
            settings.claude_model_fast: ModelUsage(),
        }

        # Request queue
        self._queue: asyncio.Queue[LLMRequest] = asyncio.Queue()

        # Worker task
        self._worker_task: Optional[asyncio.Task] = None

        # Lock for usage updates
        self._lock = asyncio.Lock()

        # LLM instances cache
        self._llm_cache: dict[str, ChatAnthropic] = {}

        logger.info(
            f"[LLM Worker] Initialized with limits - "
            f"Sonnet: {settings.sonnet_rpm} RPM, {settings.sonnet_output_tpm} output TPM | "
            f"Haiku: {settings.haiku_rpm} RPM, {settings.haiku_output_tpm} output TPM"
        )

    def _get_llm(self, model: str, max_tokens: int, temperature: float) -> ChatAnthropic:
        """Get or create an LLM instance."""
        cache_key = f"{model}:{max_tokens}:{temperature}"
        if cache_key not in self._llm_cache:
            self._llm_cache[cache_key] = ChatAnthropic(
                model=model,
                api_key=settings.anthropic_api_key,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        return self._llm_cache[cache_key]

    def _reset_if_needed(self, model: str) -> bool:
        """Reset usage if the time window has passed. Returns True if reset occurred."""
        usage = self.usage[model]
        now = time.time()
        if now - usage.window_start >= self.WINDOW_SECONDS:
            old_usage = (usage.requests, usage.input_tokens, usage.output_tokens)
            usage.requests = 0
            usage.input_tokens = 0
            usage.output_tokens = 0
            usage.window_start = now
            if any(old_usage):
                logger.debug(f"[LLM Worker] Reset window for {model}, previous usage: {old_usage}")
            return True
        return False

    def _time_until_reset(self, model: str) -> float:
        """Calculate seconds until the current window resets."""
        usage = self.usage[model]
        elapsed = time.time() - usage.window_start
        return max(0, self.WINDOW_SECONDS - elapsed)

    def _can_process(self, model: str, est_input: int, est_output: int) -> tuple[bool, str]:
        """
        Check if a request can be processed within current limits.

        Returns:
            Tuple of (can_process, reason_if_not)
        """
        limits = self.limits.get(model)
        if not limits:
            return True, ""  # Unknown model, let it through

        usage = self.usage[model]

        # Check requests per minute
        if usage.requests >= limits.rpm:
            return False, f"RPM limit ({usage.requests}/{limits.rpm})"

        # Check input tokens
        if usage.input_tokens + est_input > limits.input_tpm:
            return False, f"Input TPM ({usage.input_tokens}/{limits.input_tpm})"

        # Check output tokens
        if usage.output_tokens + est_output > limits.output_tpm:
            return False, f"Output TPM ({usage.output_tokens}/{limits.output_tpm})"

        return True, ""

    def _estimate_tokens(self, messages: List[BaseMessage]) -> int:
        """Estimate input tokens from messages (rough approximation)."""
        total_chars = sum(len(str(m.content)) for m in messages)
        # Rough estimate: 1 token ≈ 4 characters
        return total_chars // 4

    async def _process_request(self, request: LLMRequest) -> LLMResponse:
        """Process a single request, waiting if necessary. Returns LLMResponse with token usage."""
        model = request.model

        async with self._lock:
            # Reset window if needed
            self._reset_if_needed(model)

            # Wait until we can process
            can_process, reason = self._can_process(
                model,
                request.estimated_input_tokens,
                request.estimated_output_tokens
            )

            while not can_process:
                wait_time = self._time_until_reset(model)
                logger.info(
                    f"[LLM Worker] Rate limit reached for {model}: {reason}. "
                    f"Waiting {wait_time:.1f}s for window reset..."
                )

                # Release lock while waiting
                self._lock.release()
                await asyncio.sleep(wait_time + 0.5)  # Small buffer
                await self._lock.acquire()

                # Reset and check again
                self._reset_if_needed(model)
                can_process, reason = self._can_process(
                    model,
                    request.estimated_input_tokens,
                    request.estimated_output_tokens
                )

            # Reserve capacity
            usage = self.usage[model]
            usage.requests += 1
            usage.input_tokens += request.estimated_input_tokens
            usage.output_tokens += request.estimated_output_tokens

        # Make the actual API call (outside the lock)
        llm = self._get_llm(model, request.max_tokens, request.temperature)

        try:
            response = await llm.ainvoke(request.messages)

            # Extract actual token usage from response
            actual_input = request.estimated_input_tokens
            actual_output = request.estimated_output_tokens

            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                actual_output = response.usage_metadata.get('output_tokens', actual_output)
                actual_input = response.usage_metadata.get('input_tokens', actual_input)

                async with self._lock:
                    # Adjust for actual vs estimated
                    usage = self.usage[model]
                    usage.output_tokens += (actual_output - request.estimated_output_tokens)
                    usage.input_tokens += (actual_input - request.estimated_input_tokens)

            logger.debug(
                f"[LLM Worker] Completed {model} request. "
                f"Actual tokens: {actual_input} input, {actual_output} output. "
                f"Usage: {self.usage[model].requests} req, "
                f"{self.usage[model].output_tokens} output tokens"
            )

            # Return both the response and token usage
            token_usage = TokenUsage(
                input_tokens=actual_input,
                output_tokens=actual_output,
                model=model,
            )
            return LLMResponse(message=response, token_usage=token_usage)

        except Exception as e:
            # On error, release the reserved capacity
            async with self._lock:
                usage = self.usage[model]
                usage.requests = max(0, usage.requests - 1)
                usage.input_tokens = max(0, usage.input_tokens - request.estimated_input_tokens)
                usage.output_tokens = max(0, usage.output_tokens - request.estimated_output_tokens)
            raise

    async def _worker_loop(self):
        """Main worker loop that processes queued requests."""
        logger.info("[LLM Worker] Worker loop started")

        while True:
            try:
                # Get next request from queue
                request = await self._queue.get()

                try:
                    # Process the request
                    result = await self._process_request(request)
                    # Check if future is still valid (not cancelled by timeout)
                    if not request.future.done():
                        request.future.set_result(result)
                    else:
                        logger.warning("[LLM Worker] Request future already done, discarding result")
                except Exception as e:
                    # Check if future is still valid before setting exception
                    if not request.future.done():
                        request.future.set_exception(e)
                    else:
                        logger.warning(f"[LLM Worker] Request future already done, discarding exception: {e}")
                finally:
                    self._queue.task_done()

            except asyncio.CancelledError:
                logger.info("[LLM Worker] Worker loop cancelled")
                break
            except Exception as e:
                logger.error(f"[LLM Worker] Unexpected error in worker loop: {e}", exc_info=True)

    def start(self):
        """Start the worker loop."""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker_loop())
            logger.info("[LLM Worker] Started")

    def stop(self):
        """Stop the worker loop."""
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            logger.info("[LLM Worker] Stopped")

    async def submit(
        self,
        messages: List[BaseMessage],
        model: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        estimated_output_tokens: int = 2000,
    ) -> LLMResponse:
        """
        Submit a request to the worker queue.

        Args:
            messages: The messages to send to the LLM
            model: Model to use (defaults to claude_model from settings)
            max_tokens: Maximum output tokens
            temperature: Temperature for generation
            estimated_output_tokens: Estimated output tokens (for rate limiting)

        Returns:
            LLMResponse containing the message and token usage

        Raises:
            ValueError: If estimated tokens exceed the model's limit
        """
        # Ensure worker is running
        self.start()

        model = model or settings.claude_model
        estimated_input = self._estimate_tokens(messages)

        # Check if request is even possible
        limits = self.limits.get(model)
        if limits and estimated_output_tokens > limits.output_tpm:
            raise ValueError(
                f"Estimated output ({estimated_output_tokens} tokens) exceeds "
                f"the per-minute limit ({limits.output_tpm} tokens) for {model}. "
                f"Consider splitting the document or requesting a higher tier."
            )

        # Create request with future (must be created in async context)
        loop = asyncio.get_running_loop()
        request = LLMRequest(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            estimated_input_tokens=estimated_input,
            estimated_output_tokens=estimated_output_tokens,
            future=loop.create_future(),
        )

        # Add to queue
        await self._queue.put(request)

        logger.debug(
            f"[LLM Worker] Queued request for {model} "
            f"(~{estimated_input} input, ~{estimated_output_tokens} output tokens). "
            f"Queue size: {self._queue.qsize()}"
        )

        # Wait for result
        return await request.future

    def get_usage_stats(self) -> dict:
        """Get current usage statistics for all models."""
        stats = {}
        for model, usage in self.usage.items():
            limits = self.limits.get(model, ModelLimits(0, 0, 0))
            stats[model] = {
                "requests": f"{usage.requests}/{limits.rpm}",
                "input_tokens": f"{usage.input_tokens}/{limits.input_tpm}",
                "output_tokens": f"{usage.output_tokens}/{limits.output_tpm}",
                "window_remaining": f"{self._time_until_reset(model):.1f}s",
            }
        return stats


# Singleton instance
llm_worker = LLMWorker()


async def submit_to_worker(
    messages: List[BaseMessage],
    model: Optional[str] = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    estimated_output_tokens: int = 2000,
) -> LLMResponse:
    """
    Convenience function to submit a request to the global worker.

    This is the main entry point for making LLM calls throughout the application.
    Returns LLMResponse with both the message and token usage.
    """
    return await llm_worker.submit(
        messages=messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        estimated_output_tokens=estimated_output_tokens,
    )
