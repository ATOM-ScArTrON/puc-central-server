
CREATE TABLE IF NOT EXISTS key_epochs (
    epoch_number BIGINT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'RETIRED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    activated_at TIMESTAMPTZ,
    retired_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    certificate_fingerprint TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'SUSPECTED', 'REVOKED')),
    gateway BOOLEAN NOT NULL DEFAULT FALSE,
    last_seen_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS peer_links (
    device_a TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    device_b TEXT NOT NULL REFERENCES devices(device_id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'DISABLED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    disabled_at TIMESTAMPTZ,
    PRIMARY KEY (device_a, device_b),
    CHECK (device_a < device_b),
    CHECK (device_a <> device_b)
);

CREATE TABLE IF NOT EXISTS telemetry_records (
    id BIGSERIAL PRIMARY KEY,
    device_id TEXT NOT NULL REFERENCES devices(device_id),
    message_id TEXT NOT NULL,
    record_type TEXT,
    observed_at TEXT,
    payload_json JSONB NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (device_id, message_id)
);

CREATE TABLE IF NOT EXISTS audit_events (
    id BIGSERIAL PRIMARY KEY,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT,
    target_id TEXT,
    result TEXT NOT NULL,
    details_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS telemetry_device_received_idx ON telemetry_records (device_id, received_at DESC);
CREATE INDEX IF NOT EXISTS audit_created_idx ON audit_events (created_at DESC);

INSERT INTO key_epochs (epoch_number, status, activated_at)
VALUES (0, 'ACTIVE', CURRENT_TIMESTAMP)
ON CONFLICT (epoch_number) DO NOTHING;
