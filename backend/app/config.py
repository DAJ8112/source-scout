import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./referrals.db")
    request_timeout_seconds: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
    host_interval_seconds: float = float(os.getenv("HOST_INTERVAL_SECONDS", "1"))
    max_transient_retries: int = 3
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    matching_timeout_seconds: float = float(os.getenv("MATCHING_TIMEOUT_SECONDS", "45"))
    max_resume_upload_bytes: int = int(os.getenv("MAX_RESUME_UPLOAD_BYTES", str(10 * 1024 * 1024)))
    user_agent: str = os.getenv(
        "REFERRALS_USER_AGENT",
        "ReferralJobMonitorConnectorLab/0.1 (+local-personal-use)",
    )


settings = Settings()
