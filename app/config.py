"""Runtime settings, read from the environment. Secrets never leave this module in logs."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    router_base_url: str
    router_api_key: str
    router_model: str
    exa_api_key: str
    rate_per_min: int
    daily_cap: int
    max_transcript_chars: int = 120_000
    max_claim_chars: int = 600


def get_settings() -> Settings:
    return Settings(
        router_base_url=os.environ.get("ROUTER_BASE_URL", "https://router.hostinger.com/v1").rstrip("/"),
        router_api_key=os.environ.get("ROUTER_API_KEY", "").strip(),
        router_model=os.environ.get("ROUTER_MODEL", "").strip(),
        exa_api_key=os.environ.get("EXA_API_KEY", "").strip(),
        rate_per_min=int(os.environ.get("RATE_PER_MIN", "20")),
        daily_cap=int(os.environ.get("DAILY_CAP", "2000")),
    )
