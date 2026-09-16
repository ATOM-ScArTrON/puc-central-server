"""Server-side provisioning tests; kept with the central-server deployment."""

import json
import os
import tempfile

from server.central_server import ProvisioningService, derive_pairwise_key


def run_standalone():
    master = b"master-secret-for-test"
    assert derive_pairwise_key(master, "A", "B") == derive_pairwise_key(master, "B", "A")
    assert derive_pairwise_key(master, "A", "B", 1) != derive_pairwise_key(master, "A", "B", 2)
    with tempfile.TemporaryDirectory() as directory:
        registry_path = os.path.join(directory, "registry.json")
        with open(registry_path, "w", encoding="utf-8") as stream:
            json.dump({"epoch_id": 1, "devices": {"A": {"peers": ["B"]}}}, stream)
        service = ProvisioningService(registry_path, master, b"broadcast-key-12")
        payload = service.provision({"device_id": "A"})
        assert payload["device_id"] == "A"
        assert len(bytes.fromhex(payload["mission_keyset"]["B"])) == 16
        assert len(bytes.fromhex(payload["mission_broadcast_key"])) == 16
    print("[Client/Server Test] pairwise derivation: PASS")


if __name__ == "__main__":
    run_standalone()
