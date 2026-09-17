"""Main entry point: wires API and web routers and launches Uvicorn servers."""

import threading

from fastapi import FastAPI

from .api.device import router as device_router
from .web.admin import router as admin_router
from .config import (
    ADMIN_BIND, ADMIN_PORT, DATABASE_URL, SERVER_BIND, SERVER_PORT,
    TLS_CA_FILE, TLS_CERT_FILE, TLS_KEY_FILE,
)

app = FastAPI(title="PUC Central Server")
app.include_router(device_router)
app.include_router(admin_router)


@app.on_event("startup")
def startup():
    if DATABASE_URL:
        from .db import Database
        Database().initialize()


def main():
    import uvicorn

    cert = TLS_CERT_FILE
    key = TLS_KEY_FILE
    ca = TLS_CA_FILE

    device_config = uvicorn.Config(
        app, host=SERVER_BIND,
        port=SERVER_PORT,
        ssl_certfile=cert, ssl_keyfile=key, ssl_ca_certs=ca,
        # Optional client certificates keep /api/enroll reachable before the
        # device has an identity; protected device routes still require one.
        ssl_cert_reqs=1 if ca else 0, log_level="info",
    )
    admin_config = uvicorn.Config(
        app, host=ADMIN_BIND,
        port=ADMIN_PORT,
        ssl_certfile=cert, ssl_keyfile=key, log_level="info",
    )
    device_server = uvicorn.Server(device_config)
    admin_server = uvicorn.Server(admin_config)
    device_thread = threading.Thread(target=device_server.run, daemon=True)
    device_thread.start()
    admin_server.run()


if __name__ == "__main__":
    main()
