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
    # Devices only appear here after they've enrolled themselves via
    # POST /api/enroll (zero-touch). There is no manual "add device" path --
    # an admin cannot pre-register a fingerprint that a Pi hasn't presented.
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


@router.post("/admin/devices/{device_id}/peers")
def update_peers(
    device_id: str, request: Request, peers: list[str] = Form(default=[]),
    admin: str = Depends(admin_user), db: Database = Depends(get_db)
):
    db.set_peers(device_id, peers)
    epoch = db.rotate_epoch()
    db.audit(admin, "UPDATE_PEERS", "device", device_id, details={"peers": peers, "key_epoch": epoch})
    return RedirectResponse(f"/admin/devices/{device_id}", status_code=303)


@router.post("/admin/devices/{device_id}/gateway")
def set_gateway(
    device_id: str, gateway: bool = Form(False),
    admin: str = Depends(admin_user), db: Database = Depends(get_db)
):
    """Gateway status is granted here, post-enrollment, by an admin --
    never self-declared by the device at /api/enroll time."""
    if not db.set_gateway(device_id, gateway):
        raise HTTPException(status_code=404, detail="device not found")
    db.audit(admin, "SET_GATEWAY", "device", device_id, details={"gateway": gateway})
    return RedirectResponse(f"/admin/devices/{device_id}", status_code=303)


@router.post("/admin/devices/{device_id}/revoke")
def revoke_device(device_id: str, admin: str = Depends(admin_user), db: Database = Depends(get_db)):
    if not db.revoke_device(device_id):
        raise HTTPException(status_code=404, detail="device not found or already revoked")
    epoch = db.rotate_epoch()
    db.audit(admin, "REVOKE_DEVICE", "device", device_id, details={"key_epoch": epoch})
    return RedirectResponse("/admin/devices", status_code=303)


@router.post("/admin/devices/{device_id}/delete")
def delete_device(device_id: str, admin: str = Depends(admin_user), db: Database = Depends(get_db)):
    """Irreversible. Only allowed once a device is REVOKED -- revoke first,
    confirm, then delete. Records the deletion in the audit log before the
    device row disappears, so the audit trail still shows who did it."""
    try:
        deleted = db.delete_device(device_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="device not found")
    db.audit(admin, "DELETE_DEVICE", "device", device_id)
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