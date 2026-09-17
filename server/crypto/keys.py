"""Mission and pairwise key derivation helpers."""

from .ascon import ascon_xof

KEY_SIZE = 16


def derive_pairwise_key(master_secret, device_a, device_b, epoch_id=0):
    """Derive a deterministic epoch-scoped pairwise key."""
    ids = "|".join(sorted((device_a, device_b))).encode("utf-8")
    epoch = str(int(epoch_id)).encode("ascii")
    return ascon_xof(master_secret + b"pairwise-key-v2" + epoch + b"|" + ids, KEY_SIZE)
