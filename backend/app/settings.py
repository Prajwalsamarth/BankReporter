from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).parents[2]


class Settings(BaseSettings):
    """Environment configuration. Secrets are read here and nowhere else."""
    model_config = SettingsConfigDict(extra="ignore", env_file=ROOT / ".env")

    secret_key: str | None = Field(None, validation_alias="BANKREPORTER_SECRET_KEY", repr=False)
    db_path: Path = Field(ROOT / "data" / "bankreporter.sqlite", validation_alias="BANKREPORTER_DB")
    catalog_path: Path = Field(ROOT / "catalog" / "fields.yaml", validation_alias="BANKREPORTER_CATALOG")
    openai_api_key: str | None = Field(None, validation_alias="OPENAI_API_KEY", repr=False)
    llm_model: str = Field("gpt-4.1-mini", validation_alias=AliasChoices("MAPPER_LLM_MODEL"))
    b_accept: float = Field(0.85, validation_alias="MAPPER_B_ACCEPT")
    b_margin: float = Field(0.05, validation_alias="MAPPER_B_MARGIN")
    publish_schema: str = Field("lending_rpt", validation_alias="BANKREPORTER_PUBLISH_SCHEMA")
    profile_row_limit: int = Field(50_000, validation_alias="MAPPER_PROFILE_ROW_LIMIT")

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"
