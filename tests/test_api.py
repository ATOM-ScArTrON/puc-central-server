from server.main import app


def test_modular_app_exposes_expected_routes():
    paths = set(app.openapi()["paths"])
    assert {"/device/register", "/device/sync", "/api/enroll", "/admin"} <= paths
