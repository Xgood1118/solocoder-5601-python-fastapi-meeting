from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field
import uuid
import threading

from . import timeutil
from .room import room_store
from .config import config
from .notify import notify_store


class BookingStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    ENDED = "ended"


class EffectiveStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED_NOT_STARTED = "approved_not_started"
    APPROVED_IN_PROGRESS = "approved_in_progress"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    ENDED = "ended"


class Booking(BaseModel):
    id: str
    room_id: str
    user_id: str
    title: str
    start_time: datetime
    end_time: datetime
    participants: int
    amount: float = 0.0
    status: BookingStatus = BookingStatus.APPROVED
    created_at: datetime
    released_at: Optional[datetime] = None
    reminder_sent: bool = False
    approver_id: Optional[str] = None
    approval_remark: Optional[str] = None


class BookingCreate(BaseModel):
    room_id: str
    user_id: str
    title: str
    start_time: str
    end_time: str
    participants: int
    amount: float = 0.0


class BookingRelease(BaseModel):
    release_time: Optional[str] = None


class BookingRenew(BaseModel):
    new_end_time: str


class ConflictInfo(BaseModel):
    conflicting_booking_id: str
    conflicting_title: str
    conflicting_start: datetime
    conflicting_end: datetime
    conflicting_user_id: str


TERMINAL_STATUSES = {BookingStatus.ENDED, BookingStatus.CANCELLED, BookingStatus.REJECTED}

VALID_TRANSITIONS: Dict[BookingStatus, set] = {
    BookingStatus.PENDING_APPROVAL: {BookingStatus.APPROVED, BookingStatus.REJECTED, BookingStatus.CANCELLED},
    BookingStatus.APPROVED: {BookingStatus.CANCELLED, BookingStatus.ENDED},
    BookingStatus.REJECTED: set(),
    BookingStatus.CANCELLED: set(),
    BookingStatus.ENDED: set(),
}


def can_transition(current: BookingStatus, target: BookingStatus) -> bool:
    return target in VALID_TRANSITIONS.get(current, set())


def compute_effective_status(booking: Booking, now: Optional[datetime] = None) -> EffectiveStatus:
    if now is None:
        now = timeutil.now()
    s = booking.status
    if s == BookingStatus.APPROVED:
        end = booking.released_at if booking.released_at else booking.end_time
        if now < booking.start_time:
            return EffectiveStatus.APPROVED_NOT_STARTED
        elif booking.start_time <= now < end:
            return EffectiveStatus.APPROVED_IN_PROGRESS
        else:
            return EffectiveStatus.ENDED
    return EffectiveStatus(s.value)


def needs_approval(participants: int, amount: float, room_requires_approval: bool) -> bool:
    if room_requires_approval:
        return True
    if amount > config.approval_amount_threshold:
        return True
    if participants > config.approval_people_threshold:
        return True
    return False


class BookingStore:
    def __init__(self):
        self._bookings: Dict[str, Booking] = {}
        self._lock = threading.RLock()

    def _gen_id(self) -> str:
        return f"booking_{uuid.uuid4().hex[:12]}"

    def _list_active_for_room(self, room_id: str) -> List[Booking]:
        return [
            b for b in self._bookings.values()
            if b.room_id == room_id and b.status not in {
                BookingStatus.CANCELLED, BookingStatus.REJECTED, BookingStatus.ENDED,
            }
        ]

    def find_conflicts(
        self, room_id: str, start: datetime, end: datetime, exclude_booking_id: Optional[str] = None
    ) -> List[ConflictInfo]:
        conflicts = []
        for b in self._list_active_for_room(room_id):
            if exclude_booking_id and b.id == exclude_booking_id:
                continue
            b_end = b.released_at if b.released_at else b.end_time
            if timeutil.strictly_overlaps(start, end, b.start_time, b_end):
                conflicts.append(ConflictInfo(
                    conflicting_booking_id=b.id,
                    conflicting_title=b.title,
                    conflicting_start=b.start_time,
                    conflicting_end=b_end,
                    conflicting_user_id=b.user_id,
                ))
        return conflicts

    def create(self, data: BookingCreate) -> Dict[str, Any]:
        with self._lock:
            room = room_store.get(data.room_id)
            if not room:
                return {"ok": False, "error": "room not found", "status": 404}
            if room.is_disabled:
                reason = room.disabled_reason or "room is disabled"
                return {"ok": False, "error": f"room is disabled: {reason}", "status": 400}

            try:
                start = timeutil.parse_dt(data.start_time)
                end = timeutil.parse_dt(data.end_time)
            except Exception:
                return {"ok": False, "error": "invalid datetime format, use ISO 8601", "status": 400}

            err = timeutil.validate_range(start, end)
            if err:
                return {"ok": False, "error": err, "status": 400}

            now = timeutil.now()
            if end <= now:
                return {"ok": False, "error": "cannot create booking in the past", "status": 400}

            if data.participants > room.capacity:
                return {"ok": False, "error": f"participants exceed room capacity ({room.capacity})", "status": 400}

            conflicts = self.find_conflicts(data.room_id, start, end)
            if conflicts:
                return {"ok": False, "error": "time conflict", "conflicts": conflicts, "status": 409}

            status = BookingStatus.PENDING_APPROVAL if needs_approval(
                data.participants, data.amount, room.requires_approval
            ) else BookingStatus.APPROVED

            booking = Booking(
                id=self._gen_id(),
                room_id=data.room_id,
                user_id=data.user_id,
                title=data.title,
                start_time=start,
                end_time=end,
                participants=data.participants,
                amount=data.amount,
                status=status,
                created_at=timeutil.now(),
            )
            self._bookings[booking.id] = booking

            if status == BookingStatus.PENDING_APPROVAL:
                notify_store.send(
                    booking.user_id,
                    "预订待审批",
                    f"您的预订「{booking.title}」需要审批，请等待审批人处理。",
                    booking_id=booking.id,
                    notif_type="approval",
                )

            return {"ok": True, "booking": booking}

    def get(self, booking_id: str) -> Optional[Booking]:
        return self._bookings.get(booking_id)

    def list_all(self) -> List[Booking]:
        return list(self._bookings.values())

    def cancel(self, booking_id: str, user_id: str) -> Dict[str, Any]:
        with self._lock:
            b = self._bookings.get(booking_id)
            if not b:
                return {"ok": False, "error": "booking not found", "status": 404}
            if b.user_id != user_id:
                return {"ok": False, "error": "not authorized", "status": 403}
            if not can_transition(b.status, BookingStatus.CANCELLED):
                return {"ok": False, "error": f"cannot cancel from status {b.status.value}", "status": 400}
            b.status = BookingStatus.CANCELLED
            return {"ok": True, "booking": b}

    def release(self, booking_id: str, user_id: str, release_time: Optional[datetime] = None) -> Dict[str, Any]:
        with self._lock:
            b = self._bookings.get(booking_id)
            if not b:
                return {"ok": False, "error": "booking not found", "status": 404}
            if b.user_id != user_id:
                return {"ok": False, "error": "not authorized", "status": 403}
            if b.status != BookingStatus.APPROVED:
                return {"ok": False, "error": "only approved bookings can be released", "status": 400}
            now = timeutil.now()
            if release_time is None:
                release_time = now
            effective_end = b.released_at if b.released_at else b.end_time
            if release_time > effective_end:
                return {"ok": False, "error": "release time cannot be after booking end", "status": 400}
            b.released_at = release_time
            if release_time <= now:
                b.status = BookingStatus.ENDED
            notify_store.send(
                b.user_id,
                "会议室已释放",
                f"您的预订「{b.title}」已提前释放至 {release_time.strftime('%Y-%m-%d %H:%M')}。",
                booking_id=b.id,
                notif_type="info",
            )
            return {"ok": True, "booking": b}

    def renew(self, booking_id: str, user_id: str, new_end_time: datetime) -> Dict[str, Any]:
        with self._lock:
            b = self._bookings.get(booking_id)
            if not b:
                return {"ok": False, "error": "booking not found", "status": 404}
            if b.user_id != user_id:
                return {"ok": False, "error": "not authorized", "status": 403}
            if b.status != BookingStatus.APPROVED:
                return {"ok": False, "error": "only approved bookings can be renewed", "status": 400}
            now = timeutil.now()
            effective_end = b.released_at if b.released_at else b.end_time
            if now >= effective_end:
                return {"ok": False, "error": "booking already ended, cannot renew", "status": 400}
            if new_end_time <= effective_end:
                return {"ok": False, "error": "new end time must be after current end", "status": 400}
            conflicts = self.find_conflicts(b.room_id, effective_end, new_end_time, exclude_booking_id=b.id)
            if conflicts:
                return {"ok": False, "error": "renewal time conflicts with another booking", "conflicts": conflicts, "status": 409}
            if b.released_at:
                b.released_at = None
            b.end_time = new_end_time
            notify_store.send(
                b.user_id,
                "预订已续订",
                f"您的预订「{b.title}」已续订至 {new_end_time.strftime('%Y-%m-%d %H:%M')}。",
                booking_id=b.id,
                notif_type="info",
            )
            return {"ok": True, "booking": b}

    def _transition(self, booking_id: str, target: BookingStatus, **extra) -> Dict[str, Any]:
        with self._lock:
            b = self._bookings.get(booking_id)
            if not b:
                return {"ok": False, "error": "booking not found", "status": 404}
            if not can_transition(b.status, target):
                return {"ok": False, "error": f"cannot transition from {b.status.value} to {target.value}", "status": 400}
            b.status = target
            for k, v in extra.items():
                if hasattr(b, k):
                    setattr(b, k, v)
            return {"ok": True, "booking": b}

    def approve(self, booking_id: str, approver_id: str, remark: Optional[str] = None) -> Dict[str, Any]:
        result = self._transition(booking_id, BookingStatus.APPROVED, approver_id=approver_id, approval_remark=remark)
        if result.get("ok"):
            b = result["booking"]
            notify_store.send(
                b.user_id,
                "预订已批准",
                f"您的预订「{b.title}」已通过审批。" + (f" 备注: {remark}" if remark else ""),
                booking_id=b.id,
                notif_type="approval",
            )
        return result

    def reject(self, booking_id: str, approver_id: str, remark: Optional[str] = None) -> Dict[str, Any]:
        result = self._transition(booking_id, BookingStatus.REJECTED, approver_id=approver_id, approval_remark=remark)
        if result.get("ok"):
            b = result["booking"]
            notify_store.send(
                b.user_id,
                "预订已拒绝",
                f"您的预订「{b.title}」已被拒绝。" + (f" 原因: {remark}" if remark else ""),
                booking_id=b.id,
                notif_type="approval",
            )
        return result

    def check_reminders(self):
        with self._lock:
            now = timeutil.now()
            for b in self._bookings.values():
                if b.status != BookingStatus.APPROVED:
                    continue
                if b.reminder_sent:
                    continue
                effective_end = b.released_at if b.released_at else b.end_time
                if now >= effective_end:
                    continue
                minutes_to_end = timeutil.minutes_until(effective_end, now)
                if 0 <= minutes_to_end <= config.reminder_minutes_before:
                    b.reminder_sent = True
                    notify_store.send(
                        b.user_id,
                        "会议即将结束",
                        f"您的预订「{b.title}」将在 {minutes_to_end} 分钟后结束，如需续订请及时操作。",
                        booking_id=b.id,
                        notif_type="reminder",
                    )

    def auto_update_statuses(self):
        with self._lock:
            now = timeutil.now()
            for b in self._bookings.values():
                if b.status == BookingStatus.APPROVED:
                    effective_end = b.released_at if b.released_at else b.end_time
                    if now >= effective_end:
                        b.status = BookingStatus.ENDED


booking_store = BookingStore()
