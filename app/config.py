"""
Configuration module for lolo-ai-documents microservice.
Uses pydantic-settings for environment variable management.
"""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "lolo-ai-documents"
    app_version: str = "1.0.0"
    debug: bool = False
    environment: str = "development"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Claude API (Anthropic)
    anthropic_api_key: str
    claude_model: str = "claude-sonnet-4-6"  # Modelo principal (generación)
    claude_model_fast: str = "claude-haiku-4-5"  # Modelo rápido (validadores)
    claude_max_tokens: int = 8000
    claude_temperature: float = 0.3

    # Rate Limits por modelo (Tier 1 defaults - ajustar según tu tier)
    # Sonnet 4.6
    sonnet_rpm: int = 50  # Requests per minute
    sonnet_input_tpm: int = 40000  # Input tokens per minute
    sonnet_output_tpm: int = 8000  # Output tokens per minute
    # Haiku 4.5
    haiku_rpm: int = 50  # Requests per minute
    haiku_input_tpm: int = 50000  # Input tokens per minute
    haiku_output_tpm: int = 10000  # Output tokens per minute

    # MySQL Database (Read-Only)
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "db_lolo"

    # Session TTL (sessions are stored in MySQL by lolo-backend)
    session_ttl_seconds: int = 14400  # 4 hours (matches backend)

    # AWS S3
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-west-2"
    s3_bucket_name: str = "archivosstorage"
    aws_chb_path: str = "CHB/"  # S3 prefix for customer files

    # Rate Limiting
    rate_limit_analyze: str = "10/minute"
    rate_limit_generate: str = "5/minute"
    rate_limit_refine: str = "20/minute"

    # Timeouts (seconds)
    timeout_analyze: int = 30
    timeout_generate: int = 60
    timeout_refine: int = 45
    timeout_finalize: int = 30

    # CORS
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5000"]

    # Backend API (for learning system)
    backend_url: str = "http://localhost:5000"
    internal_api_key: str = "change-this-to-a-strong-internal-key"

    # Learning System
    learning_enabled: bool = True
    learning_max_per_generation: int = 20

    @property
    def mysql_connection_string(self) -> str:
        """Generate MySQL connection string."""
        return (
            f"mysql+aiomysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
        )


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Export settings instance for easy import
settings = get_settings()
