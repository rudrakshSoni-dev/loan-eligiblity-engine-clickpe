CREATE TABLE n8n_errors (
    id             bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    workflow_id    text,
    workflow_name  text        NOT NULL CHECK (btrim(workflow_name) <> ''),
    execution_id   text,
    execution_url  text,
    node_name      text,
    mode           text,
    error_message  text        NOT NULL CHECK (btrim(error_message) <> ''),
    error_stack    text,
    alert_sent_at  timestamptz,
    ses_message_id text,
    alert_error    text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    CHECK (alert_sent_at IS NULL OR alert_error IS NULL),
    CHECK (ses_message_id IS NULL OR alert_sent_at IS NOT NULL)
);

CREATE INDEX n8n_errors_created_at_idx ON n8n_errors (created_at DESC);
