from contextlib import asynccontextmanager
from datetime import date
from typing import Optional, List, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.room import room_store, RoomCreate, RoomUpdate
from app.booking import (
    booking_store,
    BookingCreate,
    BookingRelease,
    BookingRenew,
    compute_effective_status,
)
from app.approval import approval_service, ApprovalAction
from app.query import query_service, BookingWithStatus, EffectiveStatus
from app.notify import notify_store
from app import timeutil


class RoomDisable(BaseModel):
    reason: Optional[str] = None


class BookingCancel(BaseModel):
    user_id: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    async def background_tick():
        while True:
            try:
                booking_store.auto_update_statuses()
                booking_store.check_reminders()
            except Exception:
                pass
            await asyncio.sleep(30)

    task = asyncio.create_task(background_tick())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="会议室预订系统", lifespan=lifespan)


def _ok(data: Any = None) -> JSONResponse:
    return JSONResponse(status_code=200, content={"ok": True, "data": data})


def _err(msg: str, code: int = 400, extra: Optional[dict] = None) -> HTTPException:
    detail = {"ok": False, "error": msg}
    if extra:
        detail.update(extra)
    raise HTTPException(status_code=code, detail=detail)


@app.get("/health")
def health():
    return {"ok": True, "now": timeutil.now().isoformat()}


@app.get("/rooms")
def list_rooms():
    return _ok([r.model_dump(mode="json") for r in room_store.list_all()])


@app.get("/rooms/{room_id}")
def get_room(room_id: str):
    r = room_store.get(room_id)
    if not r:
        _err("room not found", 404)
    return _ok(r.model_dump(mode="json"))


@app.post("/rooms", status_code=201)
def create_room(data: RoomCreate):
    r = room_store.create(data)
    return _ok(r.model_dump(mode="json"))


@app.put("/rooms/{room_id}")
def update_room(room_id: str, data: RoomUpdate):
    r = room_store.update(room_id, data)
    if not r:
        _err("room not found", 404)
    return _ok(r.model_dump(mode="json"))


@app.post("/rooms/{room_id}/disable")
def disable_room(room_id: str, data: RoomDisable = RoomDisable()):
    r = room_store.set_disabled(room_id, True, data.reason)
    if not r:
        _err("room not found", 404)
    return _ok(r.model_dump(mode="json"))


@app.post("/rooms/{room_id}/enable")
def enable_room(room_id: str):
    r = room_store.set_disabled(room_id, False)
    if not r:
        _err("room not found", 404)
    return _ok(r.model_dump(mode="json"))


@app.delete("/rooms/{room_id}")
def delete_room(room_id: str):
    if not room_store.delete(room_id):
        _err("room not found", 404)
    return _ok()


@app.post("/bookings", status_code=201)
def create_booking(data: BookingCreate):
    result = booking_store.create(data)
    if not result.get("ok"):
        extra = {}
        if "conflicts" in result:
            extra["conflicts"] = [c.model_dump(mode="json") for c in result["conflicts"]]
        _err(result["error"], 400, extra or None)
    b = result["booking"]
    enriched = BookingWithStatus(
        **b.model_dump(mode="json"),
        effective_status=compute_effective_status(b),
    )
    return _ok(enriched.model_dump(mode="json"))


@app.get("/bookings/{booking_id}")
def get_booking(booking_id: str):
    b = query_service.get_booking_detail(booking_id)
    if not b:
        _err("booking not found", 404)
    return _ok(b.model_dump(mode="json"))


@app.post("/bookings/{booking_id}/cancel")
def cancel_booking(booking_id: str, data: BookingCancel):
    result = booking_store.cancel(booking_id, data.user_id)
    if not result.get("ok"):
        _err(result["error"])
    return _ok(result["booking"].model_dump(mode="json"))


@app.post("/bookings/{booking_id}/release")
def release_booking(booking_id: str, data: BookingRelease):
    b = booking_store.get(booking_id)
    if not b:
        _err("booking not found", 404)
    release_dt = None
    if data.release_time:
        try:
            release_dt = timeutil.parse_dt(data.release_time)
        except Exception:
            _err("invalid release_time format")
    result = booking_store.release(booking_id, b.user_id, release_dt)
    if not result.get("ok"):
        _err(result["error"])
    enriched = BookingWithStatus(
        **result["booking"].model_dump(mode="json"),
        effective_status=compute_effective_status(result["booking"]),
    )
    return _ok(enriched.model_dump(mode="json"))


@app.post("/bookings/{booking_id}/renew")
def renew_booking(booking_id: str, data: BookingRenew):
    b = booking_store.get(booking_id)
    if not b:
        _err("booking not found", 404)
    try:
        new_end = timeutil.parse_dt(data.new_end_time)
    except Exception:
        _err("invalid new_end_time format")
    result = booking_store.renew(booking_id, b.user_id, new_end)
    if not result.get("ok"):
        extra = {}
        if "conflicts" in result:
            extra["conflicts"] = [c.model_dump(mode="json") for c in result["conflicts"]]
        _err(result["error"], 400, extra or None)
    enriched = BookingWithStatus(
        **result["booking"].model_dump(mode="json"),
        effective_status=compute_effective_status(result["booking"]),
    )
    return _ok(enriched.model_dump(mode="json"))


@app.get("/approvals/pending")
def list_pending_approvals():
    bookings = approval_service.list_pending()
    enriched = [
        BookingWithStatus(**b.model_dump(mode="json"), effective_status=EffectiveStatus.PENDING_APPROVAL).model_dump(mode="json")
        for b in bookings
    ]
    return _ok(enriched)


@app.post("/approvals/{booking_id}/approve")
def approve_booking(booking_id: str, action: ApprovalAction):
    result = approval_service.approve(booking_id, action)
    if not result.get("ok"):
        _err(result["error"])
    return _ok(result["booking"].model_dump(mode="json"))


@app.post("/approvals/{booking_id}/reject")
def reject_booking(booking_id: str, action: ApprovalAction):
    result = approval_service.reject(booking_id, action)
    if not result.get("ok"):
        _err(result["error"])
    return _ok(result["booking"].model_dump(mode="json"))


@app.get("/rooms/{room_id}/bookings")
def list_room_bookings(room_id: str, d: str = Query(..., alias="date")):
    try:
        target_date = date.fromisoformat(d)
    except Exception:
        _err("invalid date format, use YYYY-MM-DD")
    if not room_store.get(room_id):
        _err("room not found", 404)
    bookings = query_service.list_room_bookings_by_date(room_id, target_date)
    return _ok([b.model_dump(mode="json") for b in bookings])


@app.get("/users/{user_id}/bookings")
def list_user_bookings(user_id: str, status: Optional[EffectiveStatus] = None):
    bookings = query_service.list_user_bookings(user_id, status)
    return _ok([b.model_dump(mode="json") for b in bookings])


@app.get("/bookings")
def list_bookings_by_status(status: EffectiveStatus):
    bookings = query_service.list_by_status(status)
    return _ok([b.model_dump(mode="json") for b in bookings])


@app.get("/bookings/in-progress/current")
def list_in_progress_bookings():
    bookings = query_service.list_in_progress()
    return _ok([b.model_dump(mode="json") for b in bookings])


@app.get("/users/{user_id}/notifications")
def list_notifications(user_id: str, unread_only: bool = False):
    notifs = notify_store.list_for_user(user_id, unread_only=unread_only)
    return _ok([n.model_dump(mode="json") for n in notifs])


@app.post("/users/{user_id}/notifications/{notif_id}/read")
def mark_notification_read(user_id: str, notif_id: str):
    if not notify_store.mark_read(user_id, notif_id):
        _err("notification not found", 404)
    return _ok()


@app.post("/users/{user_id}/notifications/read-all")
def mark_all_notifications_read(user_id: str):
    count = notify_store.mark_all_read(user_id)
    return _ok({"marked": count})
