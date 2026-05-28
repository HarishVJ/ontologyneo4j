"""
Centralized application settings using Pydantic BaseSettings.
All connection strings and configuration are loaded from .env.
Change endpoints here or in .env — no code changes needed anywhere else.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Neo4j ---
    neo4j_uri: str = "neo4j+s://f78a87d6.databases.neo4j.io"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # --- Snowflake ---
    snowflake_account: str = "lea81547-pc00894"
    snowflake_user: str = "SRV_UAT_ILINK"
    snowflake_warehouse: str = "ILINK_ANALYST_WH_XS"
    snowflake_role: str = "UAT_ILINK_RO"
    snowflake_database: str = "AIRCO_EDW_UAT"
    snowflake_schema: str = "ILINKAICHAT"
    snowflake_private_key_passphrase: str = ""
    snowflake_private_key: str = ""

    # --- Azure OpenAI ---
    azure_openai_endpoint: str = "https://igentic-demo-openai.cognitiveservices.azure.com"
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = "gpt-5.4"
    azure_openai_api_version: str = "2025-04-01-preview"

    # --- Application ---
    app_env: str = "development"
    app_log_level: str = "INFO"
    app_port: int = 8000

    @property
    def snowflake_schema_prefix(self) -> str:
        return f"{self.snowflake_database}.{self.snowflake_schema}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
