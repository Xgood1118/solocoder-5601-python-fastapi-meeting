from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from .config import config


class Room(BaseModel):
    id: str
    name: str
    floor: int
    capacity: int
    equipment: List[str] = Field(default_factory=list)
    requires_approval: bool = False
    is_disabled: bool = False
    disabled_reason: Optional[str] = None


class RoomCreate(BaseModel):
    name: str
    floor: int
    capacity: int
    equipment: List[str] = Field(default_factory=list)
    requires_approval: bool = False


class RoomUpdate(BaseModel):
    name: Optional[str] = None
    floor: Optional[int] = None
    capacity: Optional[int] = None
    equipment: Optional[List[str]] = None
    requires_approval: Optional[bool] = None


class RoomStore:
    def __init__(self):
        self._rooms: Dict[str, Room] = {}
        self._next_id = 1
        self._init_defaults()

    def _init_defaults(self):
        for r in config.default_rooms:
            room = Room(
                id=self._gen_id(),
                name=r["name"],
                floor=r["floor"],
                capacity=r["capacity"],
                equipment=r.get("equipment", []),
                requires_approval=r.get("requires_approval", False),
            )
            self._rooms[room.id] = room

    def _gen_id(self) -> str:
        rid = f"room_{self._next_id}"
        self._next_id += 1
        return rid

    def list_all(self) -> List[Room]:
        return list(self._rooms.values())

    def get(self, room_id: str) -> Optional[Room]:
        return self._rooms.get(room_id)

    def create(self, data: RoomCreate) -> Room:
        room = Room(id=self._gen_id(), **data.model_dump())
        self._rooms[room.id] = room
        return room

    def update(self, room_id: str, data: RoomUpdate) -> Optional[Room]:
        room = self._rooms.get(room_id)
        if not room:
            return None
        for k, v in data.model_dump(exclude_unset=True).items():
            setattr(room, k, v)
        return room

    def set_disabled(self, room_id: str, disabled: bool, reason: Optional[str] = None) -> Optional[Room]:
        room = self._rooms.get(room_id)
        if not room:
            return None
        room.is_disabled = disabled
        room.disabled_reason = reason if disabled else None
        return room

    def delete(self, room_id: str) -> bool:
        if room_id in self._rooms:
            del self._rooms[room_id]
            return True
        return False


room_store = RoomStore()
