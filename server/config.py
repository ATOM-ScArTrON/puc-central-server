"""Centralized environment configuration for the server tier."""

import os


DATABASE_URL = os.environ.get("DATABASE_URL", "")
TLS_CERT_FILE = os.environ.get("TLS_CERT_FILE", "")
TLS_KEY_FILE = os.environ.get("TLS_KEY_FILE", "")
TLS_CA_FILE = os.environ.get("TLS_CA_FILE", "")
TLS_CA_CERT_FILE = os.environ.get("TLS_CA_CERT_FILE", TLS_CERT_FILE)
TLS_CA_KEY_FILE = os.environ.get("TLS_CA_KEY_FILE", TLS_KEY_FILE)
SERVER_BIND = os.environ.get("SERVER_BIND", "0.0.0.0")
SERVER_PORT = int(os.environ.get("SERVER_PORT", "8443"))
ADMIN_BIND = os.environ.get("ADMIN_BIND", "127.0.0.1")
ADMIN_PORT = int(os.environ.get("ADMIN_PORT", "8444"))
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
MASTER_SERVER_SECRET_HEX = os.environ.get("MASTER_SERVER_SECRET_HEX", "")
MISSION_BROADCAST_KEY_HEX = os.environ.get("MISSION_BROADCAST_KEY_HEX", "")
ALLOW_INSECURE_IDENTITY_HEADER = os.environ.get("ALLOW_INSECURE_IDENTITY_HEADER") == "1"


def required(name, value):
    if not value:
        raise RuntimeError(f"{name} is required")
    return value
