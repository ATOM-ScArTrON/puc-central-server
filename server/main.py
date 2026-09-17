"""Main entry point: wires API and web routers and launches Uvicorn servers."""

import sys
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api.device import router as device_router
from .web.admin import router as admin_router
from .config import (
    ADMIN_BIND, ADMIN_PORT, DATABASE_URL, SERVER_BIND, SERVER_PORT,
    TLS_CA_FILE, TLS_CERT_FILE, TLS_KEY_FILE,
)

# How long to wait for the device-API listener to report itself started
# before treating it as a fatal startup failure (e.g. a port already in use).
DEVICE_SERVER_STARTUP_TIMEOUT = 10.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    if DATABASE_URL:
        from .db import Database
        Database().initialize()
    yield

app = FastAPI(title="PUC Central Server", lifespan=lifespan)
app.include_router(device_router)
app.include_router(admin_router)

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

    # uvicorn.Server.run() swallows startup exceptions (e.g. "address already
    # in use") internally and just logs + returns -- it doesn't raise into
    # the caller. Running it in a bare daemon thread means a failed bind on
    # the device API leaves the process looking healthy (admin UI still
    # comes up on its own port) while the device API silently never started.
    # Capture the exception (if any) and also watch device_server.started,
    # which uvicorn sets True once startup actually completes, so a failure
    # to bind is detected either way.
    device_error = {}

    def run_device_server():
        try:
            device_server.run()
        except Exception as exc:  # pragma: no cover - defensive
            device_error["exc"] = exc

    device_thread = threading.Thread(target=run_device_server, daemon=True)
    device_thread.start()

    deadline = time.monotonic() + DEVICE_SERVER_STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if device_error or device_server.started:
            break
        if not device_thread.is_alive():
            # The thread exited without setting device_error and without
            # ever reporting started -- treat that as a failure too.
            break
        time.sleep(0.05)

    if device_error or not device_server.started:
        reason = device_error.get(
            "exc",
            f"did not report startup within {DEVICE_SERVER_STARTUP_TIMEOUT:.0f}s "
            "(check whether the port is already in use)",
        )
        print(
            f"FATAL: device API failed to start on {SERVER_BIND}:{SERVER_PORT}: {reason}",
            file=sys.stderr,
        )
        # Don't leave a half-working server up: signal the admin listener
        # to stop instead of falling through to admin_server.run().
        device_server.should_exit = True
        sys.exit(1)

    admin_server.run()


if __name__ == "__main__":
    main()