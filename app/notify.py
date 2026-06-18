from datetime import datetime
from typing import List, Dict, Optional
from pydantic import BaseModel
import uuid


class Notification(BaseModel):
    id: str
    user_id: str
    title: str
    content: str
    created_at: datetime
    read: bool = False
    booking_id: Optional[str] = None
    type: str = "info"


class NotificationStore:
    def __init__(self):
        self._notifs: Dict[str, List[Notification]] = {}

    def _gen_id(self) -> str:
        return str(uuid.uuid4())

    def send(
        self,
        user_id: str,
        title: str,
        content: str,
        booking_id: Optional[str] = None,
        notif_type: str = "info",
    ) -> Notification:
        notif = Notification(
            id=self._gen_id(),
            user_id=user_id,
            title=title,
            content=content,
            created_at=datetime.now(),
            booking_id=booking_id,
            type=notif_type,
        )
        if user_id not in self._notifs:
            self._notifs[user_id] = []
        self._notifs[user_id].append(notif)
        return notif

    def list_for_user(self, user_id: str, unread_only: bool = False) -> List[Notification]:
        notifs = self._notifs.get(user_id, [])
        if unread_only:
            notifs = [n for n in notifs if not n.read]
        return sorted(notifs, key=lambda n: n.created_at, reverse=True)

    def mark_read(self, user_id: str, notif_id: str) -> bool:
        for n in self._notifs.get(user_id, []):
            if n.id == notif_id:
                n.read = True
                return True
        return False

    def mark_all_read(self, user_id: str) -> int:
        count = 0
        for n in self._notifs.get(user_id, []):
            if not n.read:
                n.read = True
                count += 1
        return count


notify_store = NotificationStore()
