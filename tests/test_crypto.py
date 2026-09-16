from server.crypto.ascon import ascon_xof
from server.central_server import derive_pairwise_key


def test_xof_is_deterministic_and_variable_length():
    assert ascon_xof(b"test", 32) == ascon_xof(b"test", 32)
    assert len(ascon_xof(b"test", 40)) == 40


def test_pairwise_derivation_is_symmetric_and_epoch_scoped():
    master = b"m" * 32
    assert derive_pairwise_key(master, "A", "B", 1) == derive_pairwise_key(master, "B", "A", 1)
    assert derive_pairwise_key(master, "A", "B", 1) != derive_pairwise_key(master, "A", "B", 2)
