from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import HttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR.parent / '.env', extra='ignore')
    supabase_url: HttpUrl
    supabase_key: SecretStr
    n8n_webhook_url: HttpUrl | None = None
    app_env: Literal['development', 'test', 'production'] = 'development'
    app_trigger_token: SecretStr | None = None
    scrape_cooldown_seconds: int = 300

    @field_validator('n8n_webhook_url', 'app_trigger_token', mode='before')
    @classmethod
    def empty_optional(cls, value):
        return None if value == '' else value

    @model_validator(mode='after')
    def production_token(self):
        if self.app_env == 'production' and (not self.app_trigger_token or len(self.app_trigger_token.get_secret_value()) < 24):
            raise ValueError('Production requires APP_TRIGGER_TOKEN with at least 24 characters')
        if self.scrape_cooldown_seconds < 1:
            raise ValueError('SCRAPE_COOLDOWN_SECONDS must be positive')
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
