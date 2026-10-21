"""Cold-start config validation: every problem reported at once, secrets kept out of repr."""

from pathlib import Path

import pytest

from lambdas.shared.config import (
    RDS_CA_BUNDLE,
    ConfigError,
    batch_status_config,
    load_chunk_config,
    log_level,
    split_csv_config,
    upload_url_config,
)

DB_ENV = {
    "DB_HOST": "db.internal",
    "DB_NAME": "loans",
    "DB_USER": "loans_app",
    "DB_PASSWORD": "pw-value",
}
WEBHOOK_ENV = {
    "N8N_WEBHOOK_URL": "http://10.0.0.5:5678/webhook/match-batch",
    "N8N_WEBHOOK_SECRET": "secret-value-0123456789abcdef0123",
}


def test_db_defaults_to_port_5432_and_the_bundled_rds_ca() -> None:
    config = batch_status_config(DB_ENV)
    assert config.db.port == 5432
    assert config.db.ca_bundle == RDS_CA_BUNDLE
    assert RDS_CA_BUNDLE.is_file()


def test_ca_bundle_can_be_overridden_but_never_disabled_from_env() -> None:
    config = batch_status_config({**DB_ENV, "DB_SSLROOTCERT": "/opt/ca.pem"})
    assert config.db.ca_bundle == Path("/opt/ca.pem")
    blank = batch_status_config({**DB_ENV, "DB_SSLROOTCERT": "  "})
    assert blank.db.ca_bundle == RDS_CA_BUNDLE


def test_all_missing_variables_are_reported_together() -> None:
    with pytest.raises(ConfigError) as caught:
        load_chunk_config({"DB_HOST": "db.internal"})
    message = str(caught.value)
    for name in ("DB_NAME", "DB_USER", "DB_PASSWORD", "UPLOAD_BUCKET", "N8N_WEBHOOK_SECRET"):
        assert f"{name} is missing" in message


@pytest.mark.parametrize("raw", ["0", "-5", "12MB", "1.5"])
def test_numbers_must_be_positive_integers(raw: str) -> None:
    env = {"INGEST_QUEUE_URL": "https://sqs.example/q", "MAX_UPLOAD_BYTES": raw, "CHUNK_ROWS": "5"}
    with pytest.raises(ConfigError, match="MAX_UPLOAD_BYTES must be a positive integer"):
        split_csv_config(env)


def test_split_csv_config_reads_every_value() -> None:
    env = {
        "INGEST_QUEUE_URL": "https://sqs.example/q",
        "MAX_UPLOAD_BYTES": "20971520",
        "CHUNK_ROWS": "5000",
    }
    config = split_csv_config(env)
    assert (config.max_upload_bytes, config.chunk_rows) == (20_971_520, 5000)


def test_urls_must_be_http() -> None:
    env = {**DB_ENV, **WEBHOOK_ENV, "UPLOAD_BUCKET": "b", "N8N_WEBHOOK_URL": "10.0.0.5:5678"}
    with pytest.raises(ConfigError, match="N8N_WEBHOOK_URL must be an http"):
        load_chunk_config(env)


def test_a_webhook_signing_key_shorter_than_32_characters_is_refused() -> None:
    env = {**DB_ENV, **WEBHOOK_ENV, "UPLOAD_BUCKET": "b", "N8N_WEBHOOK_SECRET": "x" * 31}
    with pytest.raises(ConfigError, match="N8N_WEBHOOK_SECRET must be at least 32 characters"):
        load_chunk_config(env)
    accepted = load_chunk_config({**env, "N8N_WEBHOOK_SECRET": "x" * 32})
    assert len(accepted.webhook.secret) == 32


def test_upload_url_config_and_custom_port() -> None:
    env = {**DB_ENV, "DB_PORT": "6543", "UPLOAD_BUCKET": "bucket", "MAX_UPLOAD_BYTES": "100"}
    config = upload_url_config(env)
    assert (config.db.port, config.bucket, config.max_upload_bytes) == (6543, "bucket", 100)


def test_secrets_never_appear_in_repr() -> None:
    config = load_chunk_config({**DB_ENV, **WEBHOOK_ENV, "UPLOAD_BUCKET": "bucket"})
    text = repr(config)
    assert "pw-value" not in text
    assert "secret-value" not in text
    assert "db.internal" in text


def test_log_level_defaults_and_rejects_unknown_values() -> None:
    assert log_level({}) == "INFO"
    assert log_level({"LOG_LEVEL": "debug"}) == "DEBUG"
    with pytest.raises(ConfigError, match="LOG_LEVEL"):
        log_level({"LOG_LEVEL": "LOUD"})
