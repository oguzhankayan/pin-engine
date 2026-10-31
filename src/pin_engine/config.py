"""Settings from .env. Keys are optional at import; each command checks the ones it needs."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"

# Pinterest limits, as Zernio documents them for pin creation.
TITLE_LIMIT = 100
DESCRIPTION_LIMIT = 800
# Text the image model draws on the pin; longer copy comes out garbled.
OVERLAY_LIMIT = 60
PIN_SIZE = "1024x1536"  # 2:3, Pinterest's recommended shape


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"

    raywake_api_key: str = ""
    raywake_base_url: str = "https://api.raywake.com"
    raywake_model: str = "openai/gpt-image-2.5/sunburst/text-to-image"
    raywake_edit_model: str = "openai/gpt-image-2.5/sunburst/edit"
    raywake_quality: str = "medium"

    zernio_api_key: str = ""
    zernio_base_url: str = "https://zernio.com/api/v1"

    pin_timezone: str = "Europe/Istanbul"

    # Optional: Etsy blocks plain page reads, so Etsy listings are read through its open API.
    # Since February 2026 the x-api-key header is "keystring:shared_secret".
    etsy_api_key: str = ""
    etsy_shared_secret: str = ""

    def require(self, *names: str) -> None:
        missing = [name.upper() for name in names if not getattr(self, name)]
        if missing:
            raise SystemExit(f"Missing {', '.join(missing)} in .env (see .env.example).")


settings = Settings()
