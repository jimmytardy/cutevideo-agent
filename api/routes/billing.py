from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


@router.post("/checkout")
async def billing_checkout_stub() -> None:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Facturation Stripe non encore implémentée",
    )
