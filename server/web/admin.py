"""Admin HTML Jinja2 routes for /admin/*."""

import hmac
import json
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from ..db import Database
from ..config import ADMIN_PASSWORD, ADMIN_USERNAME

router = APIRouter()
basic = HTTPBasic(auto_error=False)

ROOT = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))


def get_db():
    return Database()


def admin_user(credentials: HTTPBasicCredentials = Depends(basic)):
    expected_user = ADMIN_USERNAME
    expected_password = ADMIN_PASSWORD
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


@router.get("/admin", response_class=HTMLResponse)
@router.get("/admin/", response_class=HTMLResponse)
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


@router.get("/admin/devices", response_class=HTMLResponse)
def devices_page(request: Request, _: str = Depends(admin_user), db: Database = Depends(get_db)):
    return templates.TemplateResponse(request=request, name="devices.html",
                                      context={"devices": db.list_devices()})


@router.get("/admin/devices/{device_id}", response_class=HTMLResponse)
def device_page(device_id: str, request: Request, _: str = Depends(admin_user),
                db: Database = Depends(get_db)):
    device = db.device_by_id(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="device not found")
    peers = db.peer_ids(device_id)
    all_devices = [row["device_id"] for row in db.list_devices() if row["device_id"] != device_id]
    return templates.TemplateResponse(request=request, name="device.html", context={
        "device": device, "peers": peers, "all_devices": all_devices,
    })


@router.get("/admin/audit", response_class=HTMLResponse)
def audit_page(request: Request, _: str = Depends(admin_user), db: Database = Depends(get_db)):
    return templates.TemplateResponse(request=request, name="audit.html",
                                      context={"events": db.recent_audit()})


@router.post("/admin/devices")
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


@router.post("/admin/devices/{device_id}/peers")
def update_peers(
    device_id: str, request: Request, peers: list[str] = Form(default=[]),
    admin: str = Depends(admin_user), db: Database = Depends(get_db)
):
    db.set_peers(device_id, peers)
    epoch = db.rotate_epoch()
    db.audit(admin, "UPDATE_PEERS", "device", device_id, details={"peers": peers, "key_epoch": epoch})
    return RedirectResponse(f"/admin/devices/{device_id}", status_code=303)


@router.post("/admin/devices/{device_id}/revoke")
def revoke_device(device_id: str, admin: str = Depends(admin_user), db: Database = Depends(get_db)):
    if not db.revoke_device(device_id):
        raise HTTPException(status_code=404, detail="device not found or already revoked")
    epoch = db.rotate_epoch()
    db.audit(admin, "REVOKE_DEVICE", "device", device_id, details={"key_epoch": epoch})
    return RedirectResponse("/admin/devices", status_code=303)


@router.post("/admin/devices/{device_id}/reprovision")
def reprovision(device_id: str, admin: str = Depends(admin_user), db: Database = Depends(get_db)):
    device = db.device_by_id(device_id)
    if not device or device["status"] != "ACTIVE":
        raise HTTPException(status_code=400, detail="device is not active")
    epoch = db.rotate_epoch()
    db.audit(admin, "REPROVISION", "device", device_id, details={"key_epoch": epoch})
    return RedirectResponse(f"/admin/devices/{device_id}", status_code=303)


@router.get("/admin/api/devices")
def api_devices(_: str = Depends(admin_user), db: Database = Depends(get_db)):
    return JSONResponse(content=json.loads(json.dumps(db.list_devices(), default=str)))
