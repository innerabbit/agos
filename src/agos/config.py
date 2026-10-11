"""Environment-derived settings for the local AGOS vertical slice.

Only the local backends represented here are implemented.  Production service
backends are deliberately rejected rather than silently falling back to SQLite.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping, Literal

Environment = Literal["local", "staging", "production"]


class ConfigurationError(ValueError):
    """Raised for an invalid or unsupported deployment configuration."""


def _value(source: Mapping[str, str], name: str, default: str) -> str:
    return source.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    environment: Environment = "local"
    state_backend: str = "sqlite"
    memory_backend: str = "sqlite"
    execution_backend: str = "local"
    state_db_path: Path = Path("./data/agos-state.db")
    memory_db_path: Path = Path("./data/agos-memory.db")
    telemetry_mode: Literal["off", "logging"] = "logging"

    def __post_init__(self) -> None:
        if self.environment not in ("local", "staging", "production"):
            raise ConfigurationError("AGOS_ENV must be local, staging, or production")
        unsupported = {
            "AGOS_STATE_BACKEND": self.state_backend,
            "AGOS_MEMORY_BACKEND": self.memory_backend,
            "AGOS_EXECUTION_BACKEND": self.execution_backend,
        }
        expected = {"AGOS_STATE_BACKEND": "sqlite", "AGOS_MEMORY_BACKEND": "sqlite", "AGOS_EXECUTION_BACKEND": "local"}
        for variable, value in unsupported.items():
            if value != expected[variable]:
                raise ConfigurationError(
                    f"{variable}={value!r} is not implemented by this vertical slice; "
                    f"only {expected[variable]!r} is supported"
                )
        if self.telemetry_mode not in ("off", "logging"):
            raise ConfigurationError("AGOS_TELEMETRY_MODE must be off or logging")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        source = os.environ if env is None else env
        return cls(
            environment=_value(source, "AGOS_ENV", "local"),  # type: ignore[arg-type]
            state_backend=_value(source, "AGOS_STATE_BACKEND", "sqlite"),
            memory_backend=_value(source, "AGOS_MEMORY_BACKEND", "sqlite"),
            execution_backend=_value(source, "AGOS_EXECUTION_BACKEND", "local"),
            state_db_path=Path(_value(source, "AGOS_STATE_DB_PATH", "./data/agos-state.db")),
            memory_db_path=Path(_value(source, "AGOS_MEMORY_DB_PATH", "./data/agos-memory.db")),
            telemetry_mode=_value(source, "AGOS_TELEMETRY_MODE", "logging"),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class HostedAgencySettings:
    """Configuration validation for a future hosted agency deployment.

    Validation is intentionally separate from ``Settings`` so local workflows
    remain local-only.  Passing validation does not enable hosting: the
    Postgres adapter is deliberately unconfigured and fail-closed.
    """
    database_url: str
    signing_secret: str
    allowed_origins: tuple[str, ...]

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "HostedAgencySettings":
        source = os.environ if env is None else env
        database_url = source.get("DATABASE_URL", "").strip()
        signing_secret = source.get("AGOS_SIGNING_SECRET", "").strip()
        origins = tuple(origin.strip() for origin in source.get("AGOS_ALLOWED_ORIGINS", "").split(",") if origin.strip())
        if not database_url:
            raise ConfigurationError("DATABASE_URL is required for hosted agency configuration")
        if not (database_url.startswith("postgres://") or database_url.startswith("postgresql://")):
            raise ConfigurationError("DATABASE_URL must use a postgres or postgresql URL")
        if not signing_secret:
            raise ConfigurationError("AGOS_SIGNING_SECRET is required for hosted agency configuration")
        if len(signing_secret) < 32:
            raise ConfigurationError("AGOS_SIGNING_SECRET must be at least 32 characters")
        if not origins:
            raise ConfigurationError("AGOS_ALLOWED_ORIGINS must contain at least one explicit origin")
        if any("*" in origin or not origin.startswith(("https://", "http://localhost:", "http://127.0.0.1:")) for origin in origins):
            raise ConfigurationError("AGOS_ALLOWED_ORIGINS must contain explicit http(s) origins without wildcards")
        return cls(database_url, signing_secret, origins)
