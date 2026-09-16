"""Small PostgreSQL repository used by the FastAPI service."""

from contextlib import contextmanager
import json
import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


class Database:
    def __init__(self, dsn=None):
        self.dsn = dsn or os.environ.get("DATABASE_URL", "")
        if not self.dsn:
            raise RuntimeError("DATABASE_URL is required")

    @contextmanager
    def connection(self):
        with psycopg.connect(self.dsn, row_factory=dict_row) as connection:
            yield connection

    def initialize(self):
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        with self.connection() as connection:
            # Both the device and admin Uvicorn listeners use the same FastAPI
            # app, so startup can run twice concurrently in this process. The
            # advisory lock also protects initialization when two server
            # processes are started against the same database.
            connection.execute("SELECT pg_advisory_lock(739214001)")
            try:
                for statement in schema.split(";"):
                    statement = statement.strip()
                    if statement:
                        connection.execute(statement)
            finally:
                connection.execute("SELECT pg_advisory_unlock(739214001)")

    def active_epoch(self):
        with self.connection() as connection:
            row = connection.execute(
                "SELECT epoch_number FROM key_epochs WHERE status='ACTIVE' "
                "ORDER BY epoch_number DESC LIMIT 1"
            ).fetchone()
        return int(row["epoch_number"] if row else 0)

    def rotate_epoch(self):
        with self.connection() as connection:
            current = connection.execute(
                "SELECT COALESCE(MAX(epoch_number), -1) AS value FROM key_epochs"
            ).fetchone()["value"]
            next_epoch = int(current) + 1
            connection.execute(
                "UPDATE key_epochs SET status='RETIRED', retired_at=CURRENT_TIMESTAMP "
                "WHERE status='ACTIVE'"
            )
            connection.execute(
                "INSERT INTO key_epochs (epoch_number, status, activated_at) "
                "VALUES (%s, 'ACTIVE', CURRENT_TIMESTAMP)", (next_epoch,)
            )
        return next_epoch

    def device_by_id(self, device_id):
        with self.connection() as connection:
            return connection.execute(
                "SELECT * FROM devices WHERE device_id=%s", (device_id,)
            ).fetchone()

    def device_by_fingerprint(self, fingerprint):
        with self.connection() as connection:
            return connection.execute(
                "SELECT * FROM devices WHERE certificate_fingerprint=%s", (fingerprint,)
            ).fetchone()

    def list_devices(self):
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT d.*, COALESCE(array_agg(CASE WHEN p.device_a=d.device_id "
                "THEN p.device_b ELSE p.device_a END) FILTER (WHERE p.status='ACTIVE'), "
                "ARRAY[]::text[]) AS peers FROM devices d LEFT JOIN peer_links p "
                "ON d.device_id IN (p.device_a, p.device_b) GROUP BY d.device_id "
                "ORDER BY d.device_id"
            ).fetchall()
        return rows

    def peer_ids(self, device_id):
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT CASE WHEN device_a=%s THEN device_b ELSE device_a END AS peer "
                "FROM peer_links WHERE %s IN (device_a, device_b) AND status='ACTIVE' "
                "ORDER BY peer", (device_id, device_id)
            ).fetchall()
        return [row["peer"] for row in rows]

    def add_device(self, device_id, fingerprint, gateway=False):
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO devices (device_id, certificate_fingerprint, status, gateway) "
                "VALUES (%s, %s, 'ACTIVE', %s)", (device_id, fingerprint, gateway)
            )

    def set_peers(self, device_id, peers):
        peers = sorted(set(peers) - {device_id})
        with self.connection() as connection:
            known = connection.execute(
                "SELECT device_id FROM devices WHERE device_id = ANY(%s)", (peers,)
            ).fetchall()
            known_ids = {row["device_id"] for row in known}
            unknown = sorted(set(peers) - known_ids)
            if unknown:
                raise ValueError("unknown peer device(s): " + ", ".join(unknown))
            connection.execute(
                "UPDATE peer_links SET status='DISABLED', disabled_at=CURRENT_TIMESTAMP "
                "WHERE %s IN (device_a, device_b) AND status='ACTIVE'", (device_id,)
            )
            for peer in peers:
                a, b = sorted((device_id, peer))
                connection.execute(
                    "INSERT INTO peer_links (device_a, device_b, status) VALUES (%s,%s,'ACTIVE') "
                    "ON CONFLICT (device_a, device_b) DO UPDATE SET status='ACTIVE', disabled_at=NULL",
                    (a, b)
                )

    def revoke_device(self, device_id):
        with self.connection() as connection:
            result = connection.execute(
                "UPDATE devices SET status='REVOKED', revoked_at=CURRENT_TIMESTAMP "
                "WHERE device_id=%s AND status <> 'REVOKED'", (device_id,)
            )
            connection.execute(
                "UPDATE peer_links SET status='DISABLED', disabled_at=CURRENT_TIMESTAMP "
                "WHERE %s IN (device_a, device_b) AND status='ACTIVE'", (device_id,)
            )
        return result.rowcount > 0

    def set_suspected(self, device_id):
        with self.connection() as connection:
            connection.execute(
                "UPDATE devices SET status='SUSPECTED' WHERE device_id=%s AND status='ACTIVE'",
                (device_id,)
            )

    def touch_device(self, device_id):
        with self.connection() as connection:
            connection.execute(
                "UPDATE devices SET last_seen_at=CURRENT_TIMESTAMP WHERE device_id=%s",
                (device_id,)
            )

    def store_telemetry(self, device_id, records):
        accepted, duplicates, rejected = [], [], []
        with self.connection() as connection:
            for record in records:
                message_id = str(record.get("message_id", "")).strip()
                if not message_id or not isinstance(record, dict):
                    rejected.append(message_id or "<missing>")
                    continue
                existing = connection.execute(
                    "SELECT 1 FROM telemetry_records WHERE device_id=%s AND message_id=%s",
                    (device_id, message_id)
                ).fetchone()
                if existing:
                    duplicates.append(message_id)
                    continue
                payload = json.dumps(record, ensure_ascii=False)
                connection.execute(
                    "INSERT INTO telemetry_records "
                    "(device_id, message_id, record_type, observed_at, payload_json) "
                    "VALUES (%s,%s,%s,%s,%s::jsonb)",
                    (device_id, message_id, record.get("type"), record.get("timestamp"), payload)
                )
                accepted.append(message_id)
            connection.execute(
                "UPDATE devices SET last_seen_at=CURRENT_TIMESTAMP WHERE device_id=%s", (device_id,)
            )
        return {"accepted": accepted, "duplicates": duplicates, "rejected": rejected}

    def audit(self, actor, action, target_type=None, target_id=None, result="success", details=None):
        with self.connection() as connection:
            connection.execute(
                "INSERT INTO audit_events (actor, action, target_type, target_id, result, details_json) "
                "VALUES (%s,%s,%s,%s,%s,%s::jsonb)",
                (actor, action, target_type, target_id, result,
                 json.dumps(details or {}, ensure_ascii=False))
            )

    def recent_audit(self, limit=100):
        with self.connection() as connection:
            return connection.execute(
                "SELECT * FROM audit_events ORDER BY created_at DESC LIMIT %s", (limit,)
            ).fetchall()
