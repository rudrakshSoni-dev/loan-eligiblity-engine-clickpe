ALTER TABLE app_config DROP CONSTRAINT app_config_key_check;

ALTER TABLE app_config
    ADD CONSTRAINT app_config_key_check
    CHECK (key IN ('dry_run', 'test_inbox_aliases', 'max_emails_per_run', 'from_address'));

ALTER TABLE app_config
    ADD CONSTRAINT app_config_from_address_check
    CHECK (key <> 'from_address'
           OR (jsonb_typeof(value) = 'string'
               AND value #>> '{}' ~ '^[^@[:space:],;<>]+@[^@[:space:],;<>]+$'));

INSERT INTO app_config (key, value, description) VALUES
    ('from_address', '"mrrssoni12@gmail.com"',
     'sender of every Workflow C email; must be an SES-verified identity the n8n SES role may use');
