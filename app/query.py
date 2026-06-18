from datetime import date, datetime
from typing import Optional, List, Any
from pydantic import BaseModel

from . import timeutil
from .booking import (
    booking_store,
    Booking,
    BookingStatus,
    EffectiveStatus,
    compute_effective_status,
)


class BookingWithStatus(Booking):
    effective_status: EffectiveStatus


def _enrich(b: Booking, now: Optional[datetime] = None) -> BookingWithStatus:
    return BookingWithStatus(
        **b.model_dump(),
        effective_status=compute_effective_status(b, now),
    )


class QueryService:
    def list_room_bookings_by_date(self, room_id: str, d: date) -> List[BookingWithStatus]:
        booking_store.auto_update_statuses()
        now = timeutil.now()
        result = []
        for b in booking_store.list_all():
            if b.room_id != room_id:
                continue
            if b.status in {BookingStatus.CANCELLED, BookingStatus.REJECTED}:
                continue
            if timeutil.clip_to_day(d, b.start_time, b.end_time):
                result.append(_enrich(b, now))
        result.sort(key=lambda b: b.start_time)
        return result

    def list_user_bookings(
        self, user_id: str, status: Optional[EffectiveStatus] = None
    ) -> List[BookingWithStatus]:
        booking_store.auto_update_statuses()
        now = timeutil.now()
        result = []
        for b in booking_store.list_all():
            if b.user_id != user_id:
                continue
            enriched = _enrich(b, now)
            if status and enriched.effective_status != status:
                continue
            result.append(enriched)
        result.sort(key=lambda b: b.start_time, reverse=True)
        return result

    def list_in_progress(self) -> List[BookingWithStatus]:
        booking_store.auto_update_statuses()
        booking_store.check_reminders()
        now = timeutil.now()
        result = []
        for b in booking_store.list_all():
            enriched = _enrich(b, now)
            if enriched.effective_status == EffectiveStatus.APPROVED_IN_PROGRESS:
                result.append(enriched)
        result.sort(key=lambda b: b.end_time)
        return result

    def list_by_status(self, status: EffectiveStatus) -> List[BookingWithStatus]:
        booking_store.auto_update_statuses()
        now = timeutil.now()
        result = []
        for b in booking_store.list_all():
            enriched = _enrich(b, now)
            if enriched.effective_status == status:
                result.append(enriched)
        result.sort(key=lambda b: b.start_time, reverse=True)
        return result

    def get_booking_detail(self, booking_id: str) -> Optional[BookingWithStatus]:
        b = booking_store.get(booking_id)
        if not b:
            return None
        booking_store.auto_update_statuses()
        return _enrich(b)


query_service = QueryService()
