import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    username: str
    password: str
    pin: str
    region: int
    brand: int
    language: str
    api_token: str | None
    refresh_interval_minutes: float
    action_timeout_seconds: int
    data_dir: Path

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            username=os.environ["ACCOUNT_USERNAME"],
            password=os.environ["ACCOUNT_PASSWORD"],
            pin=os.environ.get("ACCOUNT_PIN", ""),
            region=int(os.environ["REGION"]),
            brand=int(os.environ["BRAND"]),
            language=os.environ.get("LANGUAGE", "en"),
            api_token=os.environ.get("API_TOKEN") or None,
            refresh_interval_minutes=float(os.environ.get("REFRESH_INTERVAL_MINUTES", "10")),
            action_timeout_seconds=int(os.environ.get("ACTION_TIMEOUT_SECONDS", "60")),
            data_dir=Path(os.environ.get("DATA_DIR", "/data")),
        )
