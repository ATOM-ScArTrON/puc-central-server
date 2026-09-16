from server.db import Database


def test_database_repository_is_modular_package():
    assert Database.__module__ == "server.db.repository"
