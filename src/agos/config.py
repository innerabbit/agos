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
