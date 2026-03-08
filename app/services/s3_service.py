"""
S3 service for file operations.
Read-only access to document files.
"""

import base64
from typing import Optional

import aioboto3
from loguru import logger

from app.config import settings


class S3Service:
    """Service for S3 file operations."""

    def __init__(self):
        self._session = aioboto3.Session(
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )

    async def get_file(self, key: str) -> Optional[bytes]:
        """
        Download a file from S3.

        Args:
            key: S3 object key

        Returns:
            File contents as bytes, or None if not found
        """
        try:
            async with self._session.client("s3") as s3:
                response = await s3.get_object(
                    Bucket=settings.s3_bucket_name,
                    Key=key,
                )
                body = await response["Body"].read()
                logger.debug(f"Downloaded file from S3: {key}")
                return body
        except Exception as e:
            logger.error(f"Failed to download from S3 {key}: {e}")
            return None

    async def get_file_base64(self, key: str) -> Optional[str]:
        """
        Download a file from S3 and return as base64.

        Args:
            key: S3 object key

        Returns:
            File contents as base64 string, or None if not found
        """
        content = await self.get_file(key)
        if content:
            return base64.b64encode(content).decode("utf-8")
        return None

    async def list_case_files(
        self,
        case_file_id: int,
        prefix: str = "",
    ) -> list[dict]:
        """
        List files associated with a case file.

        Args:
            case_file_id: ID of the case file
            prefix: Additional prefix filter

        Returns:
            List of file metadata dictionaries
        """
        try:
            # Construct the prefix based on LOLO's S3 structure
            full_prefix = f"judicial/{case_file_id}/{prefix}"

            async with self._session.client("s3") as s3:
                response = await s3.list_objects_v2(
                    Bucket=settings.s3_bucket_name,
                    Prefix=full_prefix,
                )

                files = []
                for obj in response.get("Contents", []):
                    files.append({
                        "key": obj["Key"],
                        "size": obj["Size"],
                        "last_modified": obj["LastModified"].isoformat(),
                    })

                logger.debug(f"Listed {len(files)} files for case {case_file_id}")
                return files

        except Exception as e:
            logger.error(f"Failed to list S3 files for case {case_file_id}: {e}")
            return []

    async def upload_file(
        self,
        key: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> bool:
        """
        Upload a file to S3.

        Args:
            key: S3 object key
            content: File contents
            content_type: MIME type

        Returns:
            True if successful
        """
        try:
            async with self._session.client("s3") as s3:
                await s3.put_object(
                    Bucket=settings.s3_bucket_name,
                    Key=key,
                    Body=content,
                    ContentType=content_type,
                )
                logger.info(f"Uploaded file to S3: {key}")
                return True
        except Exception as e:
            logger.error(f"Failed to upload to S3 {key}: {e}")
            return False

    async def file_exists(self, key: str) -> bool:
        """Check if a file exists in S3."""
        try:
            async with self._session.client("s3") as s3:
                await s3.head_object(
                    Bucket=settings.s3_bucket_name,
                    Key=key,
                )
                return True
        except Exception:
            return False

    async def download_file(self, key: str) -> Optional[bytes]:
        """
        Download a file from S3.
        Alias for get_file for compatibility.

        Args:
            key: S3 object key

        Returns:
            File contents as bytes, or None if not found
        """
        return await self.get_file(key)

    async def generate_presigned_url(
        self,
        key: str,
        expiration: int = 3600,
    ) -> Optional[str]:
        """
        Generate a presigned URL for temporary file access.

        Args:
            key: S3 object key
            expiration: URL expiration time in seconds (default 1 hour)

        Returns:
            Presigned URL string, or None if generation fails
        """
        try:
            async with self._session.client("s3") as s3:
                url = await s3.generate_presigned_url(
                    "get_object",
                    Params={
                        "Bucket": settings.s3_bucket_name,
                        "Key": key,
                    },
                    ExpiresIn=expiration,
                )
                logger.debug(f"Generated presigned URL for: {key}")
                return url
        except Exception as e:
            logger.error(f"Failed to generate presigned URL for {key}: {e}")
            return None
