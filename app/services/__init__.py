"""Services package."""

from app.services.mysql_service import MySQLService
from app.services.s3_service import S3Service

# NOTE: Redis has been removed. Sessions are now stored in MySQL
# in the JUDICIAL_AI_DOCUMENT_SESSION table (managed by lolo-backend).

__all__ = ["MySQLService", "S3Service"]
