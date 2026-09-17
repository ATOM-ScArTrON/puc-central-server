"""Pydantic request contracts for device endpoints."""

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=128)


class SyncRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=128)
    records: list[dict] = Field(default_factory=list)


class EnrollRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=128)
    csr_pem: str = Field(min_length=1)
    gateway: bool = False
