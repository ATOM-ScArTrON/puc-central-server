"""JSON device API routes: /device/register, /device/sync, /api/enroll."""

import hashlib
import json
import os
import ipaddress
from datetime import datetime, timezone, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..db import Database
from ..central_server import derive_pairwise_key

router = APIRouter()


def get_db():
    return Database()


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


def authorized_device(request: Request, db: Database = Depends(get_db)):
    fingerprint = client_fingerprint(request)
    device = db.device_by_fingerprint(fingerprint)
    if not device:
        raise HTTPException(status_code=403, detail="client certificate is not enrolled")
    if device["status"] != "ACTIVE":
        raise HTTPException(status_code=403, detail="device is not active")
    return device


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
        "epoch_start_time": int(datetime.now(timezone.utc).timestamp()),
        "gateway": bool(device["gateway"]),
    }


class RegisterRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=128)


class SyncRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=128)
    records: list[dict] = Field(default_factory=list)


class EnrollRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=128)
    csr_pem: str = Field(min_length=1)
    gateway: bool = False


@router.post("/device/register")
@router.post("/register")
def register(request: Request, body: RegisterRequest, db: Database = Depends(get_db)):
    device = authorized_device(request, db)
    if body.device_id != device["device_id"]:
        raise HTTPException(status_code=403, detail="device identity does not match certificate")
    db.touch_device(device["device_id"])
    db.audit(device["device_id"], "DEVICE_PROVISION", "device", device["device_id"])
    return provision_for(device, db)


@router.post("/device/sync")
@router.post("/sync")
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


@router.post("/api/enroll")
def enroll(body: EnrollRequest, db: Database = Depends(get_db)):
    """Zero-touch device enrollment.

    The Pi sends a CSR (generated locally). This endpoint:
      1. Validates the CSR.
      2. Signs it with the server CA key → issues a client certificate.
      3. Registers the certificate fingerprint in PostgreSQL.
      4. Returns the signed certificate PEM + provisioning payload.
    """
    ca_cert_path = os.environ.get("TLS_CA_CERT_FILE", os.environ.get("TLS_CERT_FILE", ""))
    ca_key_path = os.environ.get("TLS_CA_KEY_FILE", os.environ.get("TLS_KEY_FILE", ""))

    if not ca_cert_path or not ca_key_path:
        raise HTTPException(status_code=503, detail="server CA not configured for enrollment")

    try:
        csr = x509.load_pem_x509_csr(body.csr_pem.encode())
        if not csr.is_signature_valid:
            raise HTTPException(status_code=400, detail="CSR signature is invalid")
        common_names = csr.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        if not common_names or common_names[0].value != body.device_id:
            raise HTTPException(status_code=400, detail="CSR common name must match device_id")
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid CSR: {exc}") from exc

    try:
        ca_cert = x509.load_pem_x509_certificate(Path(ca_cert_path).read_bytes())
        ca_key = serialization.load_pem_private_key(
            Path(ca_key_path).read_bytes(), password=None
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"CA load error: {exc}") from exc

    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, body.device_id),
        ]))
        .issuer_name(ca_cert.subject)
        .public_key(csr.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=365 * 5))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    cert_der = cert.public_bytes(serialization.Encoding.DER)
    fingerprint = hashlib.sha256(cert_der).hexdigest()

    # Register or update the device in the database
    existing = db.device_by_id(body.device_id)
    if existing:
        # Update fingerprint if re-enrolling
        db.update_fingerprint(body.device_id, fingerprint)
    else:
        db.add_device(body.device_id, fingerprint, gateway=body.gateway)

    db.audit("enrollment", "DEVICE_ENROLL", "device", body.device_id,
             details={"fingerprint": fingerprint})

    # Build provisioning payload
    device = db.device_by_id(body.device_id)
    provision = provision_for(device, db)
    provision["certificate_pem"] = cert_pem

    return provision
