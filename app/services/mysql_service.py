"""
MySQL service for reading case file data.
Read-only access to db_lolo database.
"""

import asyncio
from datetime import datetime
from functools import wraps
from typing import Any, Callable, Optional, TypeVar

import aiomysql
from loguru import logger

from app.config import settings
from app.models.schemas import CaseContext

T = TypeVar("T")


def with_retry(max_retries: int = 3, delay: float = 1.0):
    """
    Decorator for automatic retry with reconnection on MySQL errors.

    Args:
        max_retries: Maximum number of retry attempts
        delay: Delay between retries in seconds
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(self: "MySQLService", *args, **kwargs) -> T:
            last_error = None
            for attempt in range(max_retries):
                try:
                    # Ensure connection is alive before each attempt
                    await self.ensure_connection()
                    return await func(self, *args, **kwargs)
                except (
                    aiomysql.OperationalError,
                    aiomysql.InterfaceError,
                    ConnectionResetError,
                    BrokenPipeError,
                    OSError,
                ) as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        logger.warning(
                            f"MySQL error in {func.__name__} (attempt {attempt + 1}/{max_retries}): {e}"
                        )
                        await asyncio.sleep(delay * (attempt + 1))  # Exponential backoff
                    else:
                        logger.error(
                            f"MySQL error in {func.__name__} after {max_retries} attempts: {e}"
                        )
            raise last_error
        return wrapper
    return decorator


class MySQLService:
    """Service for MySQL read operations."""

    def __init__(self):
        self._pool: Optional[aiomysql.Pool] = None

    async def connect(self) -> None:
        """Create connection pool with resilient settings for AWS RDS."""
        try:
            self._pool = await aiomysql.create_pool(
                host=settings.mysql_host,
                port=settings.mysql_port,
                user=settings.mysql_user,
                password=settings.mysql_password,
                db=settings.mysql_database,
                autocommit=True,
                minsize=1,
                maxsize=10,
                charset="utf8mb4",
                # Resilience settings for AWS RDS
                pool_recycle=300,  # Recycle connections every 5 minutes
                connect_timeout=10,  # 10 second connection timeout
                echo=False,
            )
            logger.info("Connected to MySQL with resilient pool settings")
        except Exception as e:
            logger.error(f"Failed to connect to MySQL: {e}")
            raise

    async def ensure_connection(self) -> None:
        """Ensure connection pool is alive, reconnect if needed."""
        try:
            if not self._pool or self._pool._closed:
                logger.warning("MySQL pool closed or not initialized, reconnecting...")
                await self.connect()
                return

            # Test connection
            async with self._pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1")
        except Exception as e:
            logger.warning(f"MySQL connection test failed: {e}, reconnecting...")
            if self._pool and not self._pool._closed:
                self._pool.close()
                await self._pool.wait_closed()
            await self.connect()

    async def disconnect(self) -> None:
        """Close connection pool."""
        if self._pool:
            self._pool.close()
            await self._pool.wait_closed()
            logger.info("Disconnected from MySQL")

    async def check_connection(self) -> bool:
        """Check if MySQL connection is alive."""
        try:
            if self._pool:
                async with self._pool.acquire() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute("SELECT 1")
                        return True
            return False
        except Exception:
            return False

    @with_retry(max_retries=3, delay=1.0)
    async def get_case_file_context(self, case_file_id: int) -> Optional[CaseContext]:
        """
        Get full context for a judicial case file.

        Args:
            case_file_id: ID of the JUDICIAL_CASE_FILE

        Returns:
            CaseContext with all relevant data, or None if not found
        """
        if not self._pool:
            raise RuntimeError("MySQL not connected")

        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                # Get case file with all related data
                query = """
                    SELECT
                        jcf.id_judicial_case_file as case_file_id,
                        jcf.number_case_file as case_number,
                        jcf.judgment_number,
                        jcf.process_status,
                        jcf.customer_has_bank_id as customer_has_bank_id,

                        -- Client info
                        c.id_client as client_id,
                        c.name as client_name,
                        c.dniOrRuc as client_dni_ruc,
                        c.code as client_code,

                        -- Court info
                        jc.court as court_name,

                        -- Subject and procedural way
                        js.subject as subject_name,
                        jpw.procedural_way as procedural_way_name,

                        -- Bank/Customer info
                        b.name as bank_name,
                        chb.customer_id_customer as customer_id

                    FROM JUDICIAL_CASE_FILE jcf
                    LEFT JOIN CLIENT c ON jcf.client_id_client = c.id_client
                    LEFT JOIN JUDICIAL_COURT jc ON jcf.judicial_court_id_judicial_court = jc.id_judicial_court
                    LEFT JOIN JUDICIAL_SUBJECT js ON jcf.judicial_subject_id_judicial_subject = js.id_judicial_subject
                    LEFT JOIN JUDICIAL_PROCEDURAL_WAY jpw ON jcf.judicial_procedural_way_id_judicial_procedural_way = jpw.id_judicial_procedural_way
                    LEFT JOIN CUSTOMER_HAS_BANK chb ON jcf.customer_has_bank_id = chb.id_customer_has_bank
                    LEFT JOIN BANK b ON chb.bank_id_bank = b.id_bank

                    WHERE jcf.id_judicial_case_file = %s
                    AND jcf.deleted_at IS NULL
                """
                await cur.execute(query, (case_file_id,))
                case_data = await cur.fetchone()

                if not case_data:
                    return None

                # Get recent binnacles (last 20) with their files
                binnacles_query = """
                    SELECT
                        jb.id_judicial_binnacle as id,
                        jb.date as date,
                        jb.resolution_date,
                        jbt.type_binnacle as type_name,
                        jps.procedural_stage as stage_name,
                        jb.last_performed as content

                    FROM JUDICIAL_BINNACLE jb
                    LEFT JOIN JUDICIAL_BIN_TYPE_BINNACLE jbt
                        ON jb.type_binnacle_id_type_binnacle = jbt.id_judicial_bin_type_binnacle
                    LEFT JOIN JUDICIAL_BIN_PROCEDURAL_STAGE jps
                        ON jb.judicial_bin_procedural_stage_id_judicial_bin_procedural_stage = jps.id_judicial_bin_procedural_stage

                    WHERE jb.judicial_file_case_id_judicial_file_case = %s
                    ORDER BY jb.date DESC
                    LIMIT 20
                """
                await cur.execute(binnacles_query, (case_file_id,))
                binnacles = await cur.fetchall()

                # Get binnacle IDs for file lookup
                binnacle_ids = [b["id"] for b in binnacles] if binnacles else []

                # Get files for these binnacles
                binnacle_files = []
                if binnacle_ids:
                    placeholders = ",".join(["%s"] * len(binnacle_ids))
                    files_query = f"""
                        SELECT
                            jbf.id_judicial_bin_file as id,
                            jbf.judicial_binnacle_id_judicial_binnacle as binnacle_id,
                            jbf.name_origin_aws as s3_key,
                            jbf.original_name,
                            jbf.size,
                            jb.date as binnacle_date,
                            jbt.type_binnacle as binnacle_type
                        FROM JUDICIAL_BIN_FILE jbf
                        JOIN JUDICIAL_BINNACLE jb
                            ON jbf.judicial_binnacle_id_judicial_binnacle = jb.id_judicial_binnacle
                        LEFT JOIN JUDICIAL_BIN_TYPE_BINNACLE jbt
                            ON jb.type_binnacle_id_type_binnacle = jbt.id_judicial_bin_type_binnacle
                        WHERE jbf.judicial_binnacle_id_judicial_binnacle IN ({placeholders})
                        AND jbf.deleted_at IS NULL
                        ORDER BY jb.date DESC
                        LIMIT 15
                    """
                    await cur.execute(files_query, tuple(binnacle_ids))
                    binnacle_files = await cur.fetchall()

                # Get collaterals
                collaterals_query = """
                    SELECT
                        jcol.id_judicial_collateral as id,
                        jcol.kind_of_property,
                        jcol.property_address,
                        jcol.land_area,
                        jcs.status as status_name,
                        jra.name as registration_area_name,
                        jup.name as use_of_property_name

                    FROM JUDICIAL_CASE_FILE_HAS_COLLATERAL jcfhc
                    JOIN JUDICIAL_COLLATERAL jcol ON jcfhc.judicial_collateral_id = jcol.id_judicial_collateral
                    LEFT JOIN JUDICIAL_COLLATERAL_STATUS jcs
                        ON jcol.collateral_status_id = jcs.id_judicial_collateral_status
                    LEFT JOIN JUDICIAL_REGISTRATION_AREA jra
                        ON jcol.registration_area_id = jra.id_judicial_registration_area
                    LEFT JOIN JUDICIAL_USE_OF_PROPERTY jup
                        ON jcol.use_of_property_id = jup.id_judicial_use_of_property

                    WHERE jcfhc.judicial_case_file_id = %s
                """
                await cur.execute(collaterals_query, (case_file_id,))
                collaterals = await cur.fetchall()

                # Calculate days since last action
                last_action_date = None
                days_since = None
                if binnacles and binnacles[0].get("date"):
                    last_action_date = binnacles[0]["date"]
                    if isinstance(last_action_date, datetime):
                        days_since = (datetime.utcnow() - last_action_date).days

                return CaseContext(
                    case_file_id=case_data["case_file_id"],
                    case_number=case_data["case_number"] or "",
                    client_id=case_data["client_id"] or 0,
                    client_name=case_data["client_name"] or "",
                    client_dni_ruc=case_data.get("client_dni_ruc"),
                    client_code=case_data.get("client_code"),
                    court_name=case_data.get("court_name"),
                    subject=case_data.get("subject_name"),
                    procedural_way=case_data.get("procedural_way_name"),
                    process_status=case_data.get("process_status"),
                    current_stage=case_data.get("procedural_stage_name"),
                    binnacles=[dict(b) for b in binnacles] if binnacles else [],
                    collaterals=[dict(c) for c in collaterals] if collaterals else [],
                    last_action_date=last_action_date,
                    days_since_last_action=days_since,
                    customer_has_bank_id=case_data.get("customer_has_bank_id"),
                    customer_id=case_data.get("customer_id"),
                    bank_name=case_data.get("bank_name"),
                )

    @with_retry(max_retries=3, delay=1.0)
    async def get_binnacle_files(self, case_file_id: int, limit: int = 15) -> list[dict[str, Any]]:
        """
        Get files attached to binnacles for a case file.

        Args:
            case_file_id: ID of the JUDICIAL_CASE_FILE
            limit: Maximum number of files to return

        Returns:
            List of file metadata including full S3 keys
        """
        if not self._pool:
            raise RuntimeError("MySQL not connected")

        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                # First, get case file context for S3 path construction
                case_query = """
                    SELECT
                        jcf.id_judicial_case_file,
                        jcf.customer_has_bank_id,
                        c.code as client_code,
                        chb.customer_id_customer as customer_id
                    FROM JUDICIAL_CASE_FILE jcf
                    JOIN CLIENT c ON jcf.client_id_client = c.id_client
                    JOIN CUSTOMER_HAS_BANK chb ON jcf.customer_has_bank_id = chb.id_customer_has_bank
                    WHERE jcf.id_judicial_case_file = %s
                """
                await cur.execute(case_query, (case_file_id,))
                case_info = await cur.fetchone()

                if not case_info:
                    return []

                # Now get the files
                query = """
                    SELECT
                        jbf.id_judicial_bin_file as id,
                        jbf.judicial_binnacle_id_judicial_binnacle as binnacle_id,
                        jbf.name_origin_aws as filename,
                        jbf.original_name,
                        jbf.size,
                        jb.date as binnacle_date,
                        jbt.type_binnacle as binnacle_type,
                        jb.last_performed as binnacle_content
                    FROM JUDICIAL_BIN_FILE jbf
                    JOIN JUDICIAL_BINNACLE jb
                        ON jbf.judicial_binnacle_id_judicial_binnacle = jb.id_judicial_binnacle
                    LEFT JOIN JUDICIAL_BIN_TYPE_BINNACLE jbt
                        ON jb.type_binnacle_id_type_binnacle = jbt.id_judicial_bin_type_binnacle
                    WHERE jb.judicial_file_case_id_judicial_file_case = %s
                    AND jbf.deleted_at IS NULL
                    ORDER BY jb.date DESC
                    LIMIT %s
                """
                await cur.execute(query, (case_file_id, limit))
                files = await cur.fetchall()

                if not files:
                    return []

                # Construct full S3 keys
                # Path format: {AWS_CHB_PATH}{customerId}/{chb}/{clientCode}/case-file/{caseFileId}/binnacle/{filename}
                from app.config import settings
                aws_chb_path = settings.aws_chb_path

                result = []
                for f in files:
                    file_dict = dict(f)
                    # Construct the full S3 key
                    s3_key = (
                        f"{aws_chb_path}{case_info['customer_id']}/"
                        f"{case_info['customer_has_bank_id']}/"
                        f"{case_info['client_code']}/case-file/"
                        f"{case_file_id}/binnacle/{file_dict['filename']}"
                    )
                    file_dict["s3_key"] = s3_key
                    result.append(file_dict)

                return result

    @with_retry(max_retries=3, delay=1.0)
    async def case_file_exists(self, case_file_id: int) -> bool:
        """Check if a case file exists and is not deleted."""
        if not self._pool:
            raise RuntimeError("MySQL not connected")

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                query = """
                    SELECT 1 FROM JUDICIAL_CASE_FILE
                    WHERE id_judicial_case_file = %s AND deleted_at IS NULL
                    LIMIT 1
                """
                await cur.execute(query, (case_file_id,))
                result = await cur.fetchone()
                return result is not None

    @with_retry(max_retries=3, delay=1.0)
    async def get_binnacle_types(self) -> list[dict[str, Any]]:
        """Get all binnacle types for dropdown."""
        if not self._pool:
            raise RuntimeError("MySQL not connected")

        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT id_judicial_bin_type_binnacle as id, type_binnacle as name FROM JUDICIAL_BIN_TYPE_BINNACLE ORDER BY type_binnacle"
                )
                return await cur.fetchall()

    @with_retry(max_retries=3, delay=1.0)
    async def get_procedural_stages(self) -> list[dict[str, Any]]:
        """Get all procedural stages for dropdown."""
        if not self._pool:
            raise RuntimeError("MySQL not connected")

        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT id_judicial_bin_procedural_stage as id, procedural_stage as name FROM JUDICIAL_BIN_PROCEDURAL_STAGE ORDER BY procedural_stage"
                )
                return await cur.fetchall()

    # =========================================================================
    # AI Document Session Methods
    # =========================================================================

    @with_retry(max_retries=3, delay=1.0)
    async def get_ai_session(self, session_id: str, auto_extend: bool = True) -> Optional[dict[str, Any]]:
        """
        Get AI document session by session_id.

        Automatically extends the session expiration when accessed (sliding expiration).

        Args:
            session_id: The session identifier (e.g., 'ai-doc-uuid')
            auto_extend: If True, extends session by 4 hours when accessed

        Returns:
            Session data dict or None if not found/expired
        """
        if not self._pool:
            raise RuntimeError("MySQL not connected")

        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                # First, get the session (allow recently expired sessions - within 24h grace period)
                query = """
                    SELECT
                        id_judicial_ai_document_session as id,
                        session_id,
                        judicial_case_file_id_judicial_case_file as case_file_id,
                        document_type,
                        document_name,
                        current_draft,
                        conversation_history,
                        case_context,
                        status,
                        generation_status,
                        generation_error,
                        tokens_used,
                        applied_learning_ids,
                        created_by_customer_user_id,
                        expires_at,
                        created_at,
                        updated_at
                    FROM JUDICIAL_AI_DOCUMENT_SESSION
                    WHERE session_id = %s
                    AND status = 'ACTIVE'
                    AND expires_at > DATE_SUB(NOW(), INTERVAL 24 HOUR)
                """
                await cur.execute(query, (session_id,))
                result = await cur.fetchone()

                if result and auto_extend:
                    # Auto-extend session by 4 hours (sliding expiration)
                    extend_query = """
                        UPDATE JUDICIAL_AI_DOCUMENT_SESSION
                        SET expires_at = DATE_ADD(NOW(), INTERVAL 4 HOUR),
                            updated_at = NOW()
                        WHERE session_id = %s
                        AND status = 'ACTIVE'
                    """
                    await cur.execute(extend_query, (session_id,))
                    logger.debug(f"Session {session_id[:20]}... auto-extended by 4 hours")

                if result:
                    # Parse JSON fields
                    import json
                    if isinstance(result.get("conversation_history"), str):
                        result["conversation_history"] = json.loads(
                            result["conversation_history"]
                        )
                    if isinstance(result.get("case_context"), str):
                        result["case_context"] = json.loads(result["case_context"])
                    if isinstance(result.get("applied_learning_ids"), str):
                        result["applied_learning_ids"] = json.loads(
                            result["applied_learning_ids"]
                        )
                    # Ensure applied_learning_ids is always a list
                    if result.get("applied_learning_ids") is None:
                        result["applied_learning_ids"] = []

                return result

    @with_retry(max_retries=3, delay=1.0)
    async def update_ai_session_draft(
        self,
        session_id: str,
        draft: str,
        tokens_used: int = 0,
    ) -> bool:
        """
        Update the current draft in a session and mark generation as COMPLETED.

        Args:
            session_id: The session identifier
            draft: New draft content
            tokens_used: Additional tokens to add

        Returns:
            True if updated, False if session not found
        """
        if not self._pool:
            raise RuntimeError("MySQL not connected")

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                query = """
                    UPDATE JUDICIAL_AI_DOCUMENT_SESSION
                    SET current_draft = %s,
                        tokens_used = tokens_used + %s,
                        generation_status = 'COMPLETED',
                        generation_error = NULL,
                        updated_at = NOW()
                    WHERE session_id = %s
                    AND status = 'ACTIVE'
                """
                await cur.execute(query, (draft, tokens_used, session_id))
                return cur.rowcount > 0

    @with_retry(max_retries=3, delay=1.0)
    async def update_generation_status(
        self,
        session_id: str,
        status: str,
        error: str = None,
    ) -> bool:
        """
        Update the generation status of a session.

        Args:
            session_id: The session identifier
            status: New status (NOT_STARTED, GENERATING, COMPLETED, FAILED)
            error: Error message if status is FAILED

        Returns:
            True if updated, False if session not found
        """
        if not self._pool:
            raise RuntimeError("MySQL not connected")

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                query = """
                    UPDATE JUDICIAL_AI_DOCUMENT_SESSION
                    SET generation_status = %s,
                        generation_error = %s,
                        updated_at = NOW()
                    WHERE session_id = %s
                """
                await cur.execute(query, (status, error, session_id))
                return cur.rowcount > 0

    @with_retry(max_retries=3, delay=1.0)
    async def add_ai_session_message(
        self,
        session_id: str,
        role: str,
        content: str,
        response_type: str | None = None,
        has_document_changes: bool | None = None,
    ) -> bool:
        """
        Add a message to the session's conversation history.

        Args:
            session_id: The session identifier
            role: 'user' or 'assistant'
            content: Message content
            response_type: For assistant messages - 'informational' or 'edit'
            has_document_changes: For assistant messages - whether document was modified

        Returns:
            True if updated, False if session not found
        """
        if not self._pool:
            raise RuntimeError("MySQL not connected")

        import json
        import uuid
        from datetime import datetime

        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                # Get current history
                await cur.execute(
                    "SELECT conversation_history FROM JUDICIAL_AI_DOCUMENT_SESSION "
                    "WHERE session_id = %s AND status = 'ACTIVE'",
                    (session_id,)
                )
                result = await cur.fetchone()

                if not result:
                    return False

                # Parse existing history
                history = result["conversation_history"]
                if isinstance(history, str):
                    history = json.loads(history)
                if not isinstance(history, list):
                    history = []

                # Build message object
                message = {
                    "id": str(uuid.uuid4()),
                    "role": role,
                    "content": content,
                    "timestamp": datetime.utcnow().isoformat(),
                }

                # Add optional fields for assistant messages
                if role == "assistant":
                    if response_type is not None:
                        message["responseType"] = response_type
                    if has_document_changes is not None:
                        message["hasDocumentChanges"] = has_document_changes

                history.append(message)

                # Update
                await cur.execute(
                    "UPDATE JUDICIAL_AI_DOCUMENT_SESSION "
                    "SET conversation_history = %s, updated_at = NOW() "
                    "WHERE session_id = %s",
                    (json.dumps(history), session_id)
                )
                return True

    @with_retry(max_retries=3, delay=1.0)
    async def complete_ai_session(self, session_id: str) -> bool:
        """
        Mark a session as completed.

        Args:
            session_id: The session identifier

        Returns:
            True if updated, False if session not found
        """
        if not self._pool:
            raise RuntimeError("MySQL not connected")

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                query = """
                    UPDATE JUDICIAL_AI_DOCUMENT_SESSION
                    SET status = 'COMPLETED', updated_at = NOW()
                    WHERE session_id = %s
                """
                await cur.execute(query, (session_id,))
                return cur.rowcount > 0

    @with_retry(max_retries=3, delay=1.0)
    async def update_ai_session_learning_ids(
        self,
        session_id: str,
        learning_ids: list[str],
    ) -> bool:
        """
        Update the applied learning IDs in a session.

        This is called after document generation to store which learnings
        were applied, so we can track effectiveness during refinement.

        Args:
            session_id: The session identifier
            learning_ids: List of learning IDs that were applied

        Returns:
            True if updated, False if session not found
        """
        if not self._pool:
            raise RuntimeError("MySQL not connected")

        import json

        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                query = """
                    UPDATE JUDICIAL_AI_DOCUMENT_SESSION
                    SET applied_learning_ids = %s,
                        updated_at = NOW()
                    WHERE session_id = %s
                    AND status = 'ACTIVE'
                """
                await cur.execute(query, (json.dumps(learning_ids), session_id))
                return cur.rowcount > 0

    # =========================================================================
    # Extrajudicial Context Methods
    # =========================================================================

    @with_retry(max_retries=3, delay=1.0)
    async def get_client_by_case_file(self, case_file_id: int) -> Optional[dict[str, Any]]:
        """
        Get client data from a judicial case file.

        Args:
            case_file_id: ID of the JUDICIAL_CASE_FILE

        Returns:
            Client data dict or None
        """
        if not self._pool:
            raise RuntimeError("MySQL not connected")

        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                query = """
                    SELECT
                        c.id_client as id,
                        c.code,
                        c.name,
                        c.dniOrRuc as dni_ruc,
                        c.email,
                        c.phone,
                        c.customer_has_bank_id_customer_has_bank as customer_has_bank_id,
                        n.name as negotiation_type,
                        ms.name_status as management_status,
                        f.name as funcionario_name,
                        chb.customer_id_customer as customer_id
                    FROM JUDICIAL_CASE_FILE jcf
                    JOIN CLIENT c ON jcf.client_id_client = c.id_client
                    LEFT JOIN NEGOTIATION n ON c.negotiation_id_negotiation = n.id_negotiation
                    LEFT JOIN MANAGEMENT_STATUS ms ON c.management_status_id_management_status = ms.id_management_status
                    LEFT JOIN FUNCIONARIO f ON c.funcionario_id_funcionario = f.id_funcionario
                    JOIN CUSTOMER_HAS_BANK chb ON c.customer_has_bank_id_customer_has_bank = chb.id_customer_has_bank
                    WHERE jcf.id_judicial_case_file = %s
                """
                await cur.execute(query, (case_file_id,))
                return await cur.fetchone()

    @with_retry(max_retries=3, delay=1.0)
    async def get_client_addresses(self, client_id: int) -> list[dict[str, Any]]:
        """Get all addresses for a client."""
        if not self._pool:
            return []

        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                query = """
                    SELECT
                        d.id_direction as id,
                        d.direction as address,
                        eat.address_type as address_type,
                        dep.name as department,
                        prov.name as province,
                        dist.name as district
                    FROM DIRECTION d
                    LEFT JOIN EXT_ADDRESS_TYPE eat ON d.address_type_id_address_type = eat.id_address_type
                    LEFT JOIN DEPARTMENT dep ON d.department_id_department = dep.id_department
                    LEFT JOIN PROVINCE prov ON d.province_id_province = prov.id_province
                    LEFT JOIN DISTRICT dist ON d.district_id_district = dist.id_district
                    WHERE d.client_id_client = %s
                    ORDER BY d.created_at DESC
                """
                await cur.execute(query, (client_id,))
                return await cur.fetchall()

    @with_retry(max_retries=3, delay=1.0)
    async def get_client_contacts(self, client_id: int) -> list[dict[str, Any]]:
        """Get all contacts for a client."""
        if not self._pool:
            return []

        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                query = """
                    SELECT
                        ec.id_ext_contact as id,
                        ec.name,
                        ec.phone,
                        ec.email,
                        ec.dni,
                        ect.contactType as contact_type
                    FROM EXT_CONTACT ec
                    LEFT JOIN EXT_CONTACT_TYPE ect ON ec.ext_contact_type_id_ext_contact_type = ect.id_ext_contact_type
                    WHERE ec.client_id_client = %s
                    AND ec.deleted_at IS NULL
                    ORDER BY ec.created_at DESC
                """
                await cur.execute(query, (client_id,))
                return await cur.fetchall()

    @with_retry(max_retries=3, delay=1.0)
    async def get_client_guarantors(self, client_id: int) -> list[dict[str, Any]]:
        """Get all guarantors for a client."""
        if not self._pool:
            return []

        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                query = """
                    SELECT
                        g.id_guarantor as id,
                        g.name,
                        g.phone,
                        g.email
                    FROM GUARANTOR g
                    WHERE g.client_id_client = %s
                    ORDER BY g.created_at DESC
                """
                await cur.execute(query, (client_id,))
                return await cur.fetchall()

    @with_retry(max_retries=3, delay=1.0)
    async def get_client_products(self, client_id: int) -> list[dict[str, Any]]:
        """Get all financial products for a client."""
        if not self._pool:
            return []

        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                query = """
                    SELECT
                        p.id_product as id,
                        p.code,
                        p.state,
                        epn.product_name as product_name,
                        p.judicial_case_file_id_judicial_case_file as judicial_case_file_id
                    FROM PRODUCT p
                    LEFT JOIN EXT_PRODUCT_NAME epn ON p.ext_product_name_id_ext_product_name = epn.id_ext_product_name
                    WHERE p.client_id = %s
                    ORDER BY p.id_product DESC
                """
                await cur.execute(query, (client_id,))
                return await cur.fetchall()

    @with_retry(max_retries=3, delay=1.0)
    async def get_client_agreement(self, client_id: int) -> Optional[dict[str, Any]]:
        """Get settlement agreement for a client with payments."""
        if not self._pool:
            return None

        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                # Get agreement
                query = """
                    SELECT
                        ea.id_ext_agreement as id,
                        ea.approval_date,
                        ea.total_negotiated_amount,
                        ea.paid_fees,
                        ea.judicial_fees
                    FROM EXT_AGREEMENT ea
                    WHERE ea.client_id_client = %s
                    AND ea.deleted_at IS NULL
                    ORDER BY ea.created_at DESC
                    LIMIT 1
                """
                await cur.execute(query, (client_id,))
                agreement = await cur.fetchone()

                if not agreement:
                    return None

                agreement_id = agreement["id"]

                # Get agreement products
                products_query = """
                    SELECT
                        eap.id_ext_agreement_product as id,
                        eap.account_number,
                        eap.total_debt,
                        eap.negotiated_amount,
                        eap.currency
                    FROM EXT_AGREEMENT_PRODUCT eap
                    WHERE eap.ext_agreement_id_ext_agreement = %s
                """
                await cur.execute(products_query, (agreement_id,))
                products = await cur.fetchall()

                # Get payments
                payments_query = """
                    SELECT
                        eap.id_ext_agreement_payment as id,
                        eap.payment_date,
                        eap.amount,
                        eap.comment,
                        (SELECT COUNT(*) FROM EXT_AGREEMENT_PAYMENT_VOUCHER v
                         WHERE v.ext_agreement_payment_id = eap.id_ext_agreement_payment) as voucher_count
                    FROM EXT_AGREEMENT_PAYMENT eap
                    WHERE eap.ext_agreement_id_ext_agreement = %s
                    ORDER BY eap.payment_date DESC
                """
                await cur.execute(payments_query, (agreement_id,))
                payments = await cur.fetchall()

                # Calculate totals
                total_paid = sum(float(p.get("amount", 0) or 0) for p in payments)
                total_negotiated = float(agreement.get("total_negotiated_amount", 0) or 0)

                return {
                    **agreement,
                    "products": list(products),
                    "payments": list(payments),
                    "total_paid": total_paid,
                    "pending_amount": max(0, total_negotiated - total_paid),
                }

    @with_retry(max_retries=3, delay=1.0)
    async def get_collection_history(
        self, client_id: int, limit: int = 30
    ) -> list[dict[str, Any]]:
        """Get collection action history (comments) for a client."""
        if not self._pool:
            return []

        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                query = """
                    SELECT
                        c.id_comment as id,
                        c.date,
                        c.hour,
                        c.comment,
                        ma.name_action as action_type,
                        ec.name as contact_name,
                        d.direction as address,
                        cu.name as officer_name
                    FROM COMMENT c
                    LEFT JOIN MANAGEMENT_ACTION ma ON c.management_action_id_management_action = ma.id_management_action
                    LEFT JOIN EXT_CONTACT ec ON c.ext_contact_id_ext_contact = ec.id_ext_contact
                    LEFT JOIN DIRECTION d ON c.direction_id_direction = d.id_direction
                    LEFT JOIN CUSTOMER_USER cu ON c.customer_user_id_customer_user = cu.id_customer_user
                    WHERE c.client_id_client = %s
                    ORDER BY c.date DESC, c.hour DESC
                    LIMIT %s
                """
                await cur.execute(query, (client_id, limit))
                return await cur.fetchall()

    @with_retry(max_retries=3, delay=1.0)
    async def get_client_files(
        self, client_id: int, customer_id: int, chb_id: int, client_code: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """
        Get client files with S3 paths.

        Args:
            client_id: Client ID
            customer_id: Customer ID for S3 path
            chb_id: CustomerHasBank ID for S3 path
            client_code: Client code for S3 path
            limit: Maximum files to return

        Returns:
            List of file metadata with S3 keys
        """
        if not self._pool:
            return []

        from app.config import settings

        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                query = """
                    SELECT
                        f.id_file as id,
                        f.name as filename,
                        f.originalname as original_name,
                        f.created_at,
                        et.name as tag_name
                    FROM FILE f
                    LEFT JOIN EXT_TAG et ON f.tag_id = et.id_ext_tag
                    WHERE f.id_client = %s
                    ORDER BY f.created_at DESC
                    LIMIT %s
                """
                await cur.execute(query, (client_id, limit))
                files = await cur.fetchall()

                # Build S3 keys
                result = []
                for f in files:
                    s3_key = f"{settings.aws_chb_path}{customer_id}/{chb_id}/{client_code}/{f['filename']}"
                    result.append({
                        **f,
                        "s3_key": s3_key,
                        "source": "client_file",
                    })

                return result

    @with_retry(max_retries=3, delay=1.0)
    async def get_payment_vouchers(
        self, client_id: int, customer_id: int, chb_id: int, client_code: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """
        Get payment voucher files with S3 paths.

        Args:
            client_id: Client ID
            customer_id: Customer ID for S3 path
            chb_id: CustomerHasBank ID for S3 path
            client_code: Client code for S3 path
            limit: Maximum files to return

        Returns:
            List of voucher metadata with S3 keys
        """
        if not self._pool:
            return []

        from app.config import settings

        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                query = """
                    SELECT
                        v.id_ext_agreement_payment_voucher as id,
                        v.original_name,
                        v.aws_name as filename,
                        v.size,
                        v.created_at,
                        p.id_ext_agreement_payment as payment_id,
                        p.payment_date,
                        p.amount as payment_amount,
                        ea.id_ext_agreement as agreement_id
                    FROM EXT_AGREEMENT_PAYMENT_VOUCHER v
                    JOIN EXT_AGREEMENT_PAYMENT p ON v.ext_agreement_payment_id = p.id_ext_agreement_payment
                    JOIN EXT_AGREEMENT ea ON p.ext_agreement_id_ext_agreement = ea.id_ext_agreement
                    WHERE ea.client_id_client = %s
                    AND ea.deleted_at IS NULL
                    ORDER BY p.payment_date DESC
                    LIMIT %s
                """
                await cur.execute(query, (client_id, limit))
                files = await cur.fetchall()

                # Build S3 keys
                result = []
                for f in files:
                    s3_key = (
                        f"{settings.aws_chb_path}{customer_id}/{chb_id}/{client_code}/"
                        f"agreements/{f['agreement_id']}/payments/{f['payment_id']}/{f['filename']}"
                    )
                    result.append({
                        **f,
                        "s3_key": s3_key,
                        "source": "payment_voucher",
                    })

                return result

    @with_retry(max_retries=3, delay=1.0)
    async def get_collateral_files(
        self, case_file_id: int, customer_id: int, chb_id: int, limit: int = 20
    ) -> list[dict[str, Any]]:
        """
        Get collateral files (guarantee documents) for a case file.

        Args:
            case_file_id: Judicial case file ID
            customer_id: Customer ID for S3 path
            chb_id: CustomerHasBank ID for S3 path
            limit: Maximum files to return

        Returns:
            List of collateral file metadata with S3 keys
        """
        if not self._pool:
            return []

        from app.config import settings

        async with self._pool.acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                query = """
                    SELECT
                        cf.id_judicial_collateral_files as id,
                        cf.name_origin_aws as filename,
                        cf.original_name,
                        cf.created_at,
                        c.id_judicial_collateral as collateral_id,
                        c.customer_has_bank_id_customer_has_bank as collateral_chb_id,
                        c.property_address,
                        c.kind_of_property,
                        c.electronic_record,
                        c.land_area,
                        cs.status as collateral_status
                    FROM JUDICIAL_COLLATERAL_FILES cf
                    JOIN JUDICIAL_COLLATERAL c ON cf.judicial_collateral_id_judicial_collateral = c.id_judicial_collateral
                    JOIN JUDICIAL_CASE_FILE_HAS_COLLATERAL jcfhc ON c.id_judicial_collateral = jcfhc.judicial_collateral_id
                    LEFT JOIN JUDICIAL_COLLATERAL_STATUS cs ON cf.collateral_status_id = cs.id_judicial_collateral_status
                    WHERE jcfhc.judicial_case_file_id = %s
                    AND cf.deleted_at IS NULL
                    ORDER BY cf.created_at DESC
                    LIMIT %s
                """
                await cur.execute(query, (case_file_id, limit))
                files = await cur.fetchall()

                # Build S3 keys - collateral files stored under CHB/collaterals folder
                # Path format: CHB/{chb}/collaterals/{collateralId}/{filename}
                result = []
                for f in files:
                    collateral_chb = f.get('collateral_chb_id') or chb_id
                    s3_key = (
                        f"{settings.aws_chb_path}{collateral_chb}/collaterals/"
                        f"{f['collateral_id']}/{f['filename']}"
                    )
                    result.append({
                        **f,
                        "s3_key": s3_key,
                        "source": "collateral_file",
                    })

                return result
