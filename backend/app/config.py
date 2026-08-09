import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./referrals.db")
    request_timeout_seconds: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
    host_interval_seconds: float = float(os.getenv("HOST_INTERVAL_SECONDS", "1"))
    max_transient_retries: int = 3
    user_agent: str = os.getenv(
        "REFERRALS_USER_AGENT",
        "ReferralJobMonitorConnectorLab/0.1 (+local-personal-use)",
    )


settings = Settings()
