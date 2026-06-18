from typing import Optional, Dict, Any
from pydantic import BaseModel

from .booking import booking_store, BookingStatus
from .room import room_store


class ApprovalAction(BaseModel):
    approver_id: str
    remark: Optional[str] = None


class ApprovalService:
    def approve(self, booking_id: str, action: ApprovalAction) -> Dict[str, Any]:
        b = booking_store.get(booking_id)
        if not b:
            return {"ok": False, "error": "booking not found"}
        if b.status != BookingStatus.PENDING_APPROVAL:
            return {"ok": False, "error": f"booking status is {b.status.value}, not pending_approval"}
        return booking_store.approve(booking_id, action.approver_id, action.remark)

    def reject(self, booking_id: str, action: ApprovalAction) -> Dict[str, Any]:
        b = booking_store.get(booking_id)
        if not b:
            return {"ok": False, "error": "booking not found"}
        if b.status != BookingStatus.PENDING_APPROVAL:
            return {"ok": False, "error": f"booking status is {b.status.value}, not pending_approval"}
        return booking_store.reject(booking_id, action.approver_id, action.remark)

    def list_pending(self) -> list:
        booking_store.auto_update_statuses()
        return [
            b for b in booking_store.list_all()
            if b.status == BookingStatus.PENDING_APPROVAL
        ]


approval_service = ApprovalService()
