import os
from dataclasses import dataclass


def environment_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./referrals.db")
    frontend_dist: str | None = os.getenv("FRONTEND_DIST")
    auth_required: bool = environment_flag("REFERRALS_AUTH_REQUIRED")
    app_username: str = os.getenv("APP_USERNAME", "referrals")
    app_password: str | None = os.getenv("APP_PASSWORD")
    request_timeout_seconds: float = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "30"))
    host_interval_seconds: float = float(os.getenv("HOST_INTERVAL_SECONDS", "1"))
    max_transient_retries: int = 3
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    matching_timeout_seconds: float = float(os.getenv("MATCHING_TIMEOUT_SECONDS", "45"))
    max_resume_upload_bytes: int = int(os.getenv("MAX_RESUME_UPLOAD_BYTES", str(10 * 1024 * 1024)))
    scan_interval_seconds: int = int(os.getenv("SCAN_INTERVAL_SECONDS", str(6 * 60 * 60)))
    worker_poll_seconds: float = float(os.getenv("WORKER_POLL_SECONDS", "5"))
    scan_stale_after_seconds: int = int(os.getenv("SCAN_STALE_AFTER_SECONDS", str(60 * 60)))
    user_agent: str = os.getenv(
        "REFERRALS_USER_AGENT",
        "ReferralJobMonitorConnectorLab/0.1 (+local-personal-use)",
    )


settings = Settings()
