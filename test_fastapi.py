"""Dependency-free HTTP-level tests using an in-memory repository double."""

import os
import unittest

from fastapi.testclient import TestClient

from server.app import app, get_db


class FakeDatabase:
    def __init__(self):
        self.device = {
            "device_id": "Pi-A", "certificate_fingerprint": "a" * 64,
            "status": "ACTIVE", "gateway": False,
        }
        self.epoch = 4
        self.telemetry = {}
        self.events = []

    def device_by_fingerprint(self, fingerprint):
        return self.device if fingerprint == "a" * 64 else None

    def device_by_id(self, device_id):
        return self.device if device_id == "Pi-A" else None

    def peer_ids(self, device_id):
        return ["Pi-B"] if device_id == "Pi-A" else []

    def active_epoch(self):
        return self.epoch

    def touch_device(self, device_id):
        return None

    def audit(self, *args, **kwargs):
        self.events.append((args, kwargs))

    def store_telemetry(self, device_id, records):
        accepted, duplicates, rejected = [], [], []
        for record in records:
            message_id = record.get("message_id") if isinstance(record, dict) else None
            if not message_id:
                rejected.append("<missing>")
            elif (device_id, message_id) in self.telemetry:
                duplicates.append(message_id)
            else:
                self.telemetry[(device_id, message_id)] = record
                accepted.append(message_id)
        return {"accepted": accepted, "duplicates": duplicates, "rejected": rejected}


class FastApiTests(unittest.TestCase):
    def setUp(self):
        self.database = FakeDatabase()
        app.dependency_overrides[get_db] = lambda: self.database
        os.environ["ALLOW_INSECURE_IDENTITY_HEADER"] = "1"
        os.environ["MASTER_SERVER_SECRET_HEX"] = "00" * 32

    def tearDown(self):
        app.dependency_overrides.clear()
        os.environ.pop("ALLOW_INSECURE_IDENTITY_HEADER", None)
        os.environ.pop("MASTER_SERVER_SECRET_HEX", None)

    def test_register_requires_certificate_identity_match(self):
        with TestClient(app) as client:
            response = client.post(
                "/device/register", headers={"x-client-cert-fingerprint": "a" * 64},
                json={"device_id": "Pi-A"}
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["device_id"], "Pi-A")
            self.assertEqual(response.json()["key_epoch"], 4)

            mismatch = client.post(
                "/device/register", headers={"x-client-cert-fingerprint": "a" * 64},
                json={"device_id": "Pi-B"}
            )
            self.assertEqual(mismatch.status_code, 403)

    def test_sync_acknowledges_records_and_duplicates(self):
        body = {"device_id": "Pi-A", "records": [{"message_id": "m1", "type": "VIT"}]}
        with TestClient(app) as client:
            headers = {"x-client-cert-fingerprint": "a" * 64}
            first = client.post("/device/sync", headers=headers, json=body)
            second = client.post("/device/sync", headers=headers, json=body)
            self.assertEqual(first.json()["accepted"], ["m1"])
            self.assertEqual(second.json()["duplicates"], ["m1"])


if __name__ == "__main__":
    unittest.main()
