"""Contacts / persona endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.app.dependencies.services import ServiceBundle, get_service_bundle
from backend.domain.contact import Contact, ContactStats


router = APIRouter()


class SetTypeRequest(BaseModel):
    contact_type: str


@router.get("/contacts", response_model=list[Contact])
def list_contacts(
    services: ServiceBundle = Depends(get_service_bundle),
) -> list[Contact]:
    return services.contact_repository.list_contacts()


@router.get("/contacts/stats", response_model=ContactStats)
def contact_stats(
    services: ServiceBundle = Depends(get_service_bundle),
) -> ContactStats:
    return services.contact_repository.get_stats()


@router.get("/contacts/{email}", response_model=Contact)
def get_contact(
    email: str,
    services: ServiceBundle = Depends(get_service_bundle),
) -> Contact:
    contact = services.contact_repository.get_contact(email)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found.")
    return contact


@router.put("/contacts/{email}/type", response_model=Contact)
def set_contact_type(
    email: str,
    payload: SetTypeRequest,
    services: ServiceBundle = Depends(get_service_bundle),
) -> Contact:
    valid_types = {"internal", "external", "partner", "government", "service"}
    if payload.contact_type not in valid_types:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid type. Must be one of: {', '.join(sorted(valid_types))}",
        )
    contact = services.contact_repository.set_contact_type(email, payload.contact_type)
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact not found.")
    services.session.commit()
    return contact
