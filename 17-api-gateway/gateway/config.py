"""Application configuration.

Central place for all tunable settings. Values can be overridden with
environment variables (prefixed ``GATEWAY_``) which keeps the gateway
deployable across dev / test / prod without code changes.
"""
from __future__ import annotations

import os
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent.parent


def _env(name: str, default: str) -> str:
    return os.environ.get(f"GATEWAY_{name}", default)


class Settings:
    """Configuration object.

    Reads environment variables lazily at construction time. A single
    instance is created at import (``settings``) so the app and tests
    share one configuration; tests may construct their own ``Settings``
    with overridden paths for an isolated SQLite DB.
    """

    # --- Core ---
    app_name: str = "Multi-Tenant API Gateway"
    debug: bool = _env("DEBUG", "false").lower() in {"1", "true", "yes"}
    base_dir: Path = _BASE_DIR

    # --- Secrets / crypto ---
    # Server-side secret used to HMAC-hash API keys and to sign JWTs.
    # In production this MUST come from an env var / secret manager.
    secret_key: str = _env("SECRET_KEY", "dev-secret-change-me-in-prod")
    # JWT bearer secret (kept separate so key hashing and JWT can be
    # rotated independently).
    jwt_secret: str = _env("JWT_SECRET", "dev-jwt-secret-change-me")

    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = int(_env("JWT_EXPIRE_MINUTES", "60"))

    # API key HMAC salt. The plaintext key hash uses HMAC-SHA256(key=secret,
    # msg=plaintext). A constant domain-separation prefix avoids cross-use
    # of the same bytes for key hashing vs JWT signing.
    key_hmac_pepper: str = _env("KEY_PEPPER", "api-key-hmac-v1")

    # --- Persistence ---
    database_url: str = _env(
        "DATABASE_URL", f"sqlite:///{_BASE_DIR / 'gateway.db'}"
    )

    # --- Proxy backend ---
    backend_base_url: str = _env("BACKEND_URL", "http://127.0.0.1:9000")
    proxy_timeout: float = float(_env("PROXY_TIMEOUT", "30.0"))

    # --- Rate limiting (sliding window, in-memory token bucket) ---
    rate_limit_default: int = int(_env("RATE_LIMIT_DEFAULT", "100"))  # req/min
    rate_limit_burst: int = int(_env("RATE_LIMIT_BURST", "150"))  # initial tokens
    rate_limit_window_seconds: int = int(_env("RATE_LIMIT_WINDOW_SECONDS", "60"))

    # --- Quota / plans ---
    # Monthly quotas per plan (requests). "enterprise" is unlimited (None).
    plan_quotas: dict = {
        "free": 1000,
        "starter": 10_000,
        "pro": 100_000,
        "enterprise": None,
    }
    # Webhook thresholds: notify the tenant's configured webhook when
    # monthly usage crosses these fractions of quota (stub delivery).
    quota_webhook_thresholds: tuple = (0.8, 1.0)

    # --- Usage batching ---
    usage_batch_interval_seconds: float = float(
        _env("USAGE_BATCH_INTERVAL", "5")
    )
    usage_batch_max_rows: int = int(_env("USAGE_BATCH_MAX_ROWS", "500"))

    # --- Admin dashboard auth ---
    admin_enabled: bool = _env("ADMIN_ENABLED", "true").lower() in {
        "1",
        "true",
        "yes",
    }


settings = Settings()