CREATE TABLE app_config (
    key         text        PRIMARY KEY
        CHECK (key IN ('dry_run', 'test_inbox_aliases', 'max_emails_per_run')),
    value       jsonb       NOT NULL,
    description text        NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    CHECK (key <> 'dry_run' OR jsonb_typeof(value) = 'boolean'),
    CHECK (key <> 'max_emails_per_run'
           OR (jsonb_typeof(value) = 'number' AND value::text ~ '^[1-9][0-9]{0,3}$')),
    CHECK (key <> 'test_inbox_aliases'
           OR (jsonb_typeof(value) = 'array' AND jsonb_array_length(value) > 0))
);

CREATE TRIGGER app_config_updated_at BEFORE UPDATE ON app_config
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

INSERT INTO app_config (key, value, description) VALUES
    ('dry_run', 'true',
     'true = Workflow C composes and checks emails but sends nothing'),
    ('test_inbox_aliases',
     '["mrrssoni12@gmail.com", "mrrssoni12+one@gmail.com", "mrrssoni12+two@gmail.com"]',
     'the only addresses Workflow C may deliver to; each user is mapped to one by user_id'),
    ('max_emails_per_run', '5',
     'cap on emails composed (and later sent) per Workflow C run');
