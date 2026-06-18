import os
import yaml
from pathlib import Path
from typing import List, Dict, Any


class Config:
    def __init__(self):
        self.approval_amount_threshold: float = 5000.0
        self.approval_people_threshold: int = 20
        self.reminder_minutes_before: int = 15
        self.default_rooms: List[Dict[str, Any]] = []
        self._load()

    def _load(self):
        config_path = Path(__file__).parent.parent / "config.yaml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        else:
            data = {}

        approval = data.get("approval", {})
        self.approval_amount_threshold = float(
            os.getenv("APPROVAL_AMOUNT_THRESHOLD", approval.get("amount_threshold", 5000))
        )
        self.approval_people_threshold = int(
            os.getenv("APPROVAL_PEOPLE_THRESHOLD", approval.get("people_threshold", 20))
        )

        reminder = data.get("reminder", {})
        self.reminder_minutes_before = int(
            os.getenv("REMINDER_MINUTES_BEFORE", reminder.get("minutes_before", 15))
        )

        self.default_rooms = data.get("default_rooms", [])


config = Config()
