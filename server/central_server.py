"""Compatibility exports and launcher for the FastAPI central server."""

import json
import os
import threading

from .crypto.ascon import ascon_xof


KEY_SIZE = 16


def derive_pairwise_key(master_secret, device_a, device_b, epoch_id=0):
    """Derive a deterministic epoch-scoped pairwise key."""
    ids = "|".join(sorted((device_a, device_b))).encode("utf-8")
    epoch = str(int(epoch_id)).encode("ascii")
    return ascon_xof(master_secret + b"pairwise-key-v2" + epoch + b"|" + ids, KEY_SIZE)


class ProvisioningService:
    def __init__(self, registry_path, master_secret, broadcast_key):
        self.registry_path = registry_path
        self.master_secret = bytes(master_secret)
        self.broadcast_key = bytes(broadcast_key)
        self._lock = threading.Lock()
        self.registry = self._load_registry()

    def _load_registry(self):
        try:
            with open(self.registry_path, "r", encoding="utf-8") as stream:
                return json.load(stream)
        except (OSError, json.JSONDecodeError):
            return {"devices": {}}

    def provision(self, request):
        device_id = str(request.get("device_id", "")).strip()
        if not device_id:
            raise ValueError("device_id is required")
        with self._lock:
            device = self.registry.get("devices", {}).get(device_id)
            if not device:
                raise PermissionError("device is not registered")
            peers = device.get("peers", [])
            epoch = int(self.registry.get("epoch_id", 0))
            keyset = {
                peer_id: derive_pairwise_key(self.master_secret, device_id, peer_id, epoch).hex()
                for peer_id in peers
            }
            return {
                "device_id": device_id,
                "mission_keyset": keyset,
                "mission_broadcast_key": self.broadcast_key.hex(),
                "mission_epoch_id": epoch,
                "key_epoch": epoch,
                "epoch_start_time": self.registry.get("epoch_start_time", 0),
                "gateway": bool(device.get("gateway", False)),
            }

def main():
    from .app import main as run_fastapi
    run_fastapi()


if __name__ == "__main__":
    main()
