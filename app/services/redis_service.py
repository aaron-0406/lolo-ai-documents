"""
Redis service for session management.
"""

import json
from typing import Any, Optional

import redis.asyncio as redis
from loguru import logger

from app.config import settings


class RedisService:
    """Service for Redis operations (session storage)."""

    def __init__(self):
        self._client: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Connect to Redis."""
        try:
            self._client = redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            await self._client.ping()
            logger.info("Connected to Redis")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._client:
            await self._client.close()
            logger.info("Disconnected from Redis")

    async def check_connection(self) -> bool:
        """Check if Redis connection is alive."""
        try:
            if self._client:
                await self._client.ping()
                return True
            return False
        except Exception:
            return False

    async def set_session(
        self,
        session_id: str,
        data: dict[str, Any],
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """
        Store session data.

        Args:
            session_id: Unique session identifier
            data: Session data to store
            ttl_seconds: Time-to-live in seconds (default from settings)
        """
        if not self._client:
            raise RuntimeError("Redis not connected")

        ttl = ttl_seconds or settings.session_ttl_seconds
        key = f"ai_doc_session:{session_id}"

        await self._client.setex(
            key,
            ttl,
            json.dumps(data, default=str),
        )
        logger.debug(f"Session {session_id} stored with TTL {ttl}s")

    async def get_session(self, session_id: str) -> Optional[dict[str, Any]]:
        """
        Retrieve session data.

        Args:
            session_id: Session identifier

        Returns:
            Session data or None if not found/expired
        """
        if not self._client:
            raise RuntimeError("Redis not connected")

        key = f"ai_doc_session:{session_id}"
        data = await self._client.get(key)

        if data:
            logger.debug(f"Session {session_id} retrieved")
            return json.loads(data)

        logger.debug(f"Session {session_id} not found")
        return None

    async def update_session(
        self,
        session_id: str,
        data: dict[str, Any],
        refresh_ttl: bool = True,
    ) -> bool:
        """
        Update existing session data.

        Args:
            session_id: Session identifier
            data: New session data
            refresh_ttl: Whether to refresh TTL

        Returns:
            True if updated, False if session not found
        """
        if not self._client:
            raise RuntimeError("Redis not connected")

        key = f"ai_doc_session:{session_id}"

        # Check if exists
        exists = await self._client.exists(key)
        if not exists:
            return False

        if refresh_ttl:
            await self._client.setex(
                key,
                settings.session_ttl_seconds,
                json.dumps(data, default=str),
            )
        else:
            # Keep existing TTL
            ttl = await self._client.ttl(key)
            if ttl > 0:
                await self._client.setex(key, ttl, json.dumps(data, default=str))
            else:
                await self._client.set(key, json.dumps(data, default=str))

        logger.debug(f"Session {session_id} updated")
        return True

    async def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.

        Args:
            session_id: Session identifier

        Returns:
            True if deleted, False if not found
        """
        if not self._client:
            raise RuntimeError("Redis not connected")

        key = f"ai_doc_session:{session_id}"
        result = await self._client.delete(key)

        if result:
            logger.debug(f"Session {session_id} deleted")
            return True
        return False

    async def extend_session_ttl(
        self,
        session_id: str,
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        """
        Extend session TTL without modifying data.

        Args:
            session_id: Session identifier
            ttl_seconds: New TTL in seconds

        Returns:
            True if extended, False if session not found
        """
        if not self._client:
            raise RuntimeError("Redis not connected")

        key = f"ai_doc_session:{session_id}"
        ttl = ttl_seconds or settings.session_ttl_seconds

        result = await self._client.expire(key, ttl)
        return bool(result)
