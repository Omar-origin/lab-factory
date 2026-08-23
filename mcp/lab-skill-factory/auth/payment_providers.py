"""Payment-provider boundary for the Lab Factory commercial control plane.

Manual providers record a customer's claim for seller verification.  They never
mark an order paid.  A future Paddle adapter must verify a signed webhook before
returning a completed payment event.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class PaymentProvider(Protocol):
    provider_id: str

    def public_config(self) -> dict[str, Any]: ...

    def validate_submission(self, reference: str, paid_at: str) -> None: ...


@dataclass(frozen=True)
class ManualPaymentProvider:
    provider_id: str
    label: str
    payment_url: str = ""
    instructions: str = ""
    qr_image_url: str = ""

    def public_config(self) -> dict[str, Any]:
        return {
            "id": self.provider_id,
            "label": self.label,
            "payment_url": self.payment_url,
            "instructions": self.instructions,
            "qr_image_url": self.qr_image_url,
            "verification": "manual",
            "available": bool(self.payment_url or self.instructions or self.qr_image_url),
        }

    def validate_submission(self, reference: str, paid_at: str) -> None:
        if not reference.strip():
            raise ValueError("payment_reference is required for manual verification")
        if len(reference.strip()) > 120:
            raise ValueError("payment_reference is too long")
        if not paid_at.strip() or len(paid_at.strip()) > 64:
            raise ValueError("paid_at is required and must be at most 64 characters")


@dataclass(frozen=True)
class PaddlePaymentProvider:
    """Disabled-by-default seam for a later verified Paddle webhook adapter."""

    provider_id: str = "paddle"

    def public_config(self) -> dict[str, Any]:
        return {
            "id": self.provider_id,
            "label": "Paddle",
            "payment_url": "",
            "instructions": "审核通过后开放",
            "qr_image_url": "",
            "verification": "webhook",
            "available": False,
        }

    def validate_submission(self, reference: str, paid_at: str) -> None:
        raise ValueError("Paddle orders must be confirmed by a verified webhook")
