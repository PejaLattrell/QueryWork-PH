from functools import lru_cache
from math import isfinite
from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR.parent / '.env', extra='ignore')
    supabase_url: HttpUrl
    supabase_key: SecretStr
    supabase_service_role_key: SecretStr | None = None
    fx_usd_rates: dict[str, float] = Field(default_factory=dict)
    ingestion_landing_dir: Path = BASE_DIR.parent / 'data' / 'landing'
    app_env: Literal['development', 'test', 'production'] = 'development'
    app_trigger_token: SecretStr | None = None
    scrape_cooldown_seconds: int = 300

    @field_validator('supabase_service_role_key', 'app_trigger_token', mode='before')
    @classmethod
    def empty_optional(cls, value):
        return None if value == '' else value

    @field_validator('fx_usd_rates')
    @classmethod
    def positive_exchange_rates(cls, value):
        if any(not isfinite(rate) or rate <= 0 for rate in value.values()):
            raise ValueError('FX_USD_RATES must contain positive, finite USD-per-currency rates')
        return {currency.upper(): rate for currency, rate in value.items()}

    @field_validator('ingestion_landing_dir')
    @classmethod
    def landing_path(cls, value):
        return value if value.is_absolute() else BASE_DIR.parent / value

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
