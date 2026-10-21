"""Typed Lambda settings read from environment variables, validated once at cold start.

Each Lambda builds its config at import time, so a missing or malformed variable fails the
cold start with one ConfigError that names every problem, instead of failing mid-request.
The variable names match serverless.yml.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

RDS_CA_BUNDLE = Path(__file__).resolve().parent / "rds-global-bundle.pem"

DEFAULT_DB_PORT = 5432
MIN_SIGNING_KEY_CHARS = 32
LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR"})


class ConfigError(Exception):
    """One or more environment variables are missing or invalid."""


class _EnvReader:
    """Collects every problem before raising, so one deploy fixes them all."""

    def __init__(self, env: Mapping[str, str]) -> None:
        self._env = env
        self.problems: list[str] = []

    def text(self, name: str) -> str:
        value = self._env.get(name, "").strip()
        if not value:
            self.problems.append(f"{name} is missing")
        return value

    def optional_text(self, name: str) -> str | None:
        return self._env.get(name, "").strip() or None

    def positive_int(self, name: str, default: int | None = None) -> int:
        raw = self._env.get(name, "").strip()
        if not raw and default is not None:
            return default
        if not raw:
            self.problems.append(f"{name} is missing")
            return 0
        if not raw.isdigit() or int(raw) <= 0:
            self.problems.append(f"{name} must be a positive integer, got {raw!r}")
            return 0
        return int(raw)

    def http_url(self, name: str) -> str:
        value = self.text(name)
        if value and not value.startswith(("http://", "https://")):
            self.problems.append(f"{name} must be an http(s) URL")
        return value

    def raise_if_invalid(self) -> None:
        if self.problems:
            raise ConfigError("; ".join(self.problems))


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    database: str
    user: str
    password: str
    ca_bundle: Path | None

    @classmethod
    def read(cls, env: _EnvReader) -> DbConfig:
        override = env.optional_text("DB_SSLROOTCERT")
        return cls(
            host=env.text("DB_HOST"),
            port=env.positive_int("DB_PORT", DEFAULT_DB_PORT),
            database=env.text("DB_NAME"),
            user=env.text("DB_USER"),
            password=env.text("DB_PASSWORD"),
            ca_bundle=Path(override) if override else RDS_CA_BUNDLE,
        )

    def __repr__(self) -> str:
        return f"DbConfig(host={self.host!r}, port={self.port}, database={self.database!r})"


@dataclass(frozen=True)
class WebhookConfig:
    url: str
    secret: str

    @classmethod
    def read(cls, env: _EnvReader) -> WebhookConfig:
        secret = env.text("N8N_WEBHOOK_SECRET")
        if secret and len(secret) < MIN_SIGNING_KEY_CHARS:
            env.problems.append(
                f"N8N_WEBHOOK_SECRET must be at least {MIN_SIGNING_KEY_CHARS} characters"
                " (HS256 signing key)"
            )
        return cls(url=env.http_url("N8N_WEBHOOK_URL"), secret=secret)

    def __repr__(self) -> str:
        return f"WebhookConfig(url={self.url!r})"


@dataclass(frozen=True)
class UploadUrlConfig:
    db: DbConfig
    bucket: str
    max_upload_bytes: int


@dataclass(frozen=True)
class SplitCsvConfig:
    queue_url: str
    max_upload_bytes: int
    chunk_rows: int


@dataclass(frozen=True)
class LoadChunkConfig:
    db: DbConfig
    bucket: str
    webhook: WebhookConfig


@dataclass(frozen=True)
class BatchStatusConfig:
    db: DbConfig


def log_level(env: Mapping[str, str]) -> str:
    level = env.get("LOG_LEVEL", "INFO").strip().upper() or "INFO"
    if level not in LOG_LEVELS:
        raise ConfigError(f"LOG_LEVEL must be one of {sorted(LOG_LEVELS)}, got {level!r}")
    return level


def upload_url_config(env: Mapping[str, str]) -> UploadUrlConfig:
    reader = _EnvReader(env)
    config = UploadUrlConfig(
        db=DbConfig.read(reader),
        bucket=reader.text("UPLOAD_BUCKET"),
        max_upload_bytes=reader.positive_int("MAX_UPLOAD_BYTES"),
    )
    reader.raise_if_invalid()
    return config


def split_csv_config(env: Mapping[str, str]) -> SplitCsvConfig:
    reader = _EnvReader(env)
    config = SplitCsvConfig(
        queue_url=reader.http_url("INGEST_QUEUE_URL"),
        max_upload_bytes=reader.positive_int("MAX_UPLOAD_BYTES"),
        chunk_rows=reader.positive_int("CHUNK_ROWS"),
    )
    reader.raise_if_invalid()
    return config


def load_chunk_config(env: Mapping[str, str]) -> LoadChunkConfig:
    reader = _EnvReader(env)
    config = LoadChunkConfig(
        db=DbConfig.read(reader),
        bucket=reader.text("UPLOAD_BUCKET"),
        webhook=WebhookConfig.read(reader),
    )
    reader.raise_if_invalid()
    return config


def batch_status_config(env: Mapping[str, str]) -> BatchStatusConfig:
    reader = _EnvReader(env)
    config = BatchStatusConfig(db=DbConfig.read(reader))
    reader.raise_if_invalid()
    return config
