"""Main entry point: wires API and web routers and launches Uvicorn servers."""

import os
import threading

from fastapi import FastAPI

from .api.device import router as device_router
from .web.admin import router as admin_router

app = FastAPI(title="PUC Central Server")
app.include_router(device_router)
app.include_router(admin_router)


@app.on_event("startup")
def startup():
    if os.environ.get("DATABASE_URL"):
        from .db import Database
        Database().initialize()


def main():
    import uvicorn

    cert = os.environ.get("TLS_CERT_FILE")
    key = os.environ.get("TLS_KEY_FILE")
    ca = os.environ.get("TLS_CA_FILE")

    device_config = uvicorn.Config(
        app, host=os.environ.get("SERVER_BIND", "0.0.0.0"),
        port=int(os.environ.get("SERVER_PORT", "8443")),
        ssl_certfile=cert, ssl_keyfile=key, ssl_ca_certs=ca,
        # Optional client certificates keep /api/enroll reachable before the
        # device has an identity; protected device routes still require one.
        ssl_cert_reqs=1 if ca else 0, log_level="info",
    )
    admin_config = uvicorn.Config(
        app, host=os.environ.get("ADMIN_BIND", "127.0.0.1"),
        port=int(os.environ.get("ADMIN_PORT", "8444")),
        ssl_certfile=cert, ssl_keyfile=key, log_level="info",
    )
    device_server = uvicorn.Server(device_config)
    admin_server = uvicorn.Server(admin_config)
    device_thread = threading.Thread(target=device_server.run, daemon=True)
    device_thread.start()
    admin_server.run()


if __name__ == "__main__":
    main()
