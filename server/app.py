"""FastAPI provisioning, telemetry, and server-rendered administration app."""

import hashlib
import hmac
import json
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from .central_server import derive_pairwise_key
from .db import Database


ROOT = Path(__file__).parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))
app = FastAPI(title="PUC Central Server")
basic = HTTPBasic(auto_error=False)


def get_db():
    return Database()


def admin_user(credentials: HTTPBasicCredentials = Depends(basic)):
    expected_user = os.environ.get("ADMIN_USERNAME", "admin")
    expected_password = os.environ.get("ADMIN_PASSWORD", "")
    if not credentials or not expected_password or not (
        hmac.compare_digest(credentials.username, expected_user)
        and hmac.compare_digest(credentials.password, expected_password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="administrator authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def client_fingerprint(request: Request):
    """Read the peer certificate fingerprint from the TLS connection.

    The development-only header fallback is disabled unless explicitly enabled.
    A reverse proxy may set the header after terminating mTLS, but it must not
    be reachable directly by untrusted clients.
    """
    transport = request.scope.get("transport")
    ssl_object = transport.get_extra_info("ssl_object") if transport else None
    if ssl_object:
        certificate = ssl_object.getpeercert(binary_form=True)
        if certificate:
            return hashlib.sha256(certificate).hexdigest()
    if os.environ.get("ALLOW_INSECURE_IDENTITY_HEADER") == "1":
        return request.headers.get("x-client-cert-fingerprint", "").lower()
    raise HTTPException(status_code=401, detail="client certificate required")


def authorized_device(request: Request, db: Database):
    fingerprint = client_fingerprint(request)
    device = db.device_by_fingerprint(fingerprint)
    if not device:
        raise HTTPException(status_code=403, detail="client certificate is not enrolled")
    if device["status"] != "ACTIVE":
        raise HTTPException(status_code=403, detail="device is not active")
    return device


class RegisterRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=128)


class SyncRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=128)
    records: list[dict] = Field(default_factory=list)


def provision_for(device, db):
    epoch = db.active_epoch()
    master = bytes.fromhex(os.environ["MASTER_SERVER_SECRET_HEX"])
    peers = db.peer_ids(device["device_id"])
    keyset = {
        peer: derive_pairwise_key(master, device["device_id"], peer, epoch).hex()
        for peer in peers
    }
    broadcast = os.environ.get("MISSION_BROADCAST_KEY_HEX", "")
    return {
        "device_id": device["device_id"],
        "mission_keyset": keyset,
        "mission_broadcast_key": broadcast,
        "key_epoch": epoch,
        "mission_epoch_id": epoch,
        "epoch_start_time": 0,
        "gateway": bool(device["gateway"]),
    }


@app.on_event("startup")
def startup():
    if os.environ.get("DATABASE_URL"):
        get_db().initialize()


@app.post("/device/register")
@app.post("/register")
def register(request: Request, body: RegisterRequest, db: Database = Depends(get_db)):
    device = authorized_device(request, db)
    if body.device_id != device["device_id"]:
        raise HTTPException(status_code=403, detail="device identity does not match certificate")
    db.touch_device(device["device_id"])
    db.audit(device["device_id"], "DEVICE_PROVISION", "device", device["device_id"])
    return provision_for(device, db)


@app.post("/device/sync")
@app.post("/sync")
def sync(request: Request, body: SyncRequest, db: Database = Depends(get_db)):
    device = authorized_device(request, db)
    if body.device_id != device["device_id"]:
        raise HTTPException(status_code=403, detail="device identity does not match certificate")
    if len(body.records) > 1000:
        raise HTTPException(status_code=413, detail="too many records in one request")
    result = db.store_telemetry(device["device_id"], body.records)
    db.audit(device["device_id"], "TELEMETRY_SYNC", "device", device["device_id"], details={
        "accepted": len(result["accepted"]),
        "duplicates": len(result["duplicates"]),
        "rejected": len(result["rejected"]),
    })
    return result


@app.get("/admin", response_class=HTMLResponse)
@app.get("/admin/", response_class=HTMLResponse)
def dashboard(request: Request, _: str = Depends(admin_user), db: Database = Depends(get_db)):
    devices = db.list_devices()
    counts = {
        "active": sum(row["status"] == "ACTIVE" for row in devices),
        "suspected": sum(row["status"] == "SUSPECTED" for row in devices),
        "revoked": sum(row["status"] == "REVOKED" for row in devices),
    }
    return templates.TemplateResponse(request=request, name="dashboard.html", context={
        "devices": devices, "counts": counts, "epoch": db.active_epoch(),
    })


@app.get("/admin/devices", response_class=HTMLResponse)
def devices_page(request: Request, _: str = Depends(admin_user), db: Database = Depends(get_db)):
    return templates.TemplateResponse(request=request, name="devices.html", context={"devices": db.list_devices()})


@app.get("/admin/devices/{device_id}", response_class=HTMLResponse)
def device_page(device_id: str, request: Request, _: str = Depends(admin_user), db: Database = Depends(get_db)):
    device = db.device_by_id(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="device not found")
    peers = db.peer_ids(device_id)
    all_devices = [row["device_id"] for row in db.list_devices() if row["device_id"] != device_id]
    return templates.TemplateResponse(request=request, name="device.html", context={
        "device": device, "peers": peers, "all_devices": all_devices,
    })


@app.get("/admin/audit", response_class=HTMLResponse)
def audit_page(request: Request, _: str = Depends(admin_user), db: Database = Depends(get_db)):
    return templates.TemplateResponse(request=request, name="audit.html", context={"events": db.recent_audit()})


@app.post("/admin/devices")
def add_device(
    request: Request, device_id: str = Form(...), certificate_fingerprint: str = Form(...),
    gateway: bool = Form(False), admin: str = Depends(admin_user), db: Database = Depends(get_db)
):
    fingerprint = certificate_fingerprint.strip().lower().replace(":", "")
    if len(fingerprint) != 64 or any(c not in "0123456789abcdef" for c in fingerprint):
        raise HTTPException(status_code=400, detail="certificate fingerprint must be SHA-256 hex")
    db.add_device(device_id.strip(), fingerprint, gateway)
    db.audit(admin, "ADD_DEVICE", "device", device_id.strip(), details={"fingerprint": fingerprint})
    return RedirectResponse("/admin/devices", status_code=303)


@app.post("/admin/devices/{device_id}/peers")
def update_peers(
    device_id: str, request: Request, peers: list[str] = Form(default=[]),
    admin: str = Depends(admin_user), db: Database = Depends(get_db)
):
    db.set_peers(device_id, peers)
    epoch = db.rotate_epoch()
    db.audit(admin, "UPDATE_PEERS", "device", device_id, details={"peers": peers, "key_epoch": epoch})
    return RedirectResponse(f"/admin/devices/{device_id}", status_code=303)


@app.post("/admin/devices/{device_id}/revoke")
def revoke_device(device_id: str, admin: str = Depends(admin_user), db: Database = Depends(get_db)):
    if not db.revoke_device(device_id):
        raise HTTPException(status_code=404, detail="device not found or already revoked")
    epoch = db.rotate_epoch()
    db.audit(admin, "REVOKE_DEVICE", "device", device_id, details={"key_epoch": epoch})
    return RedirectResponse("/admin/devices", status_code=303)


@app.post("/admin/devices/{device_id}/reprovision")
def reprovision(device_id: str, admin: str = Depends(admin_user), db: Database = Depends(get_db)):
    device = db.device_by_id(device_id)
    if not device or device["status"] != "ACTIVE":
        raise HTTPException(status_code=400, detail="device is not active")
    epoch = db.rotate_epoch()
    db.audit(admin, "REPROVISION", "device", device_id, details={"key_epoch": epoch})
    return RedirectResponse(f"/admin/devices/{device_id}", status_code=303)


@app.get("/admin/api/devices")
def api_devices(_: str = Depends(admin_user), db: Database = Depends(get_db)):
    return JSONResponse(content=json.loads(json.dumps(db.list_devices(), default=str)))


def main():
    import uvicorn
    import threading

    cert = os.environ.get("TLS_CERT_FILE")
    key = os.environ.get("TLS_KEY_FILE")
    ca = os.environ.get("TLS_CA_FILE")

    device_config = uvicorn.Config(
        app, host=os.environ.get("SERVER_BIND", "0.0.0.0"),
        port=int(os.environ.get("SERVER_PORT", "8443")),
        ssl_certfile=cert, ssl_keyfile=key, ssl_ca_certs=ca,
        ssl_cert_reqs=2 if ca else 0, log_level="info",
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
