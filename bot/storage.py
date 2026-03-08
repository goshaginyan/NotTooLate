"""Per-user JSON file storage for Telegram bot dates."""

import asyncio
import json
import os
import time
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

# Per-user locks to prevent concurrent writes to the same file
_locks: dict[int, asyncio.Lock] = {}


def _get_lock(user_id: int) -> asyncio.Lock:
    if user_id not in _locks:
        _locks[user_id] = asyncio.Lock()
    return _locks[user_id]


def _user_file(user_id: int) -> Path:
    return DATA_DIR / f"{user_id}.json"


def _load(user_id: int) -> list[dict]:
    path = _user_file(user_id)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(user_id: int, events: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(_user_file(user_id), "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False, indent=2)


def add_event(user_id: int, name: str, day: int, month: int, event_type: str) -> dict:
    events = _load(user_id)
    event = {
        "id": int(time.time() * 1000),
        "name": name,
        "day": day,
        "month": month,
        "type": event_type,
    }
    events.append(event)
    _save(user_id, events)
    return event


def get_events(user_id: int) -> list[dict]:
    return _load(user_id)


def get_event(user_id: int, event_id: int) -> dict | None:
    for e in _load(user_id):
        if e["id"] == event_id:
            return e
    return None


def update_event(user_id: int, event_id: int, **fields) -> dict | None:
    events = _load(user_id)
    for e in events:
        if e["id"] == event_id:
            e.update(fields)
            _save(user_id, events)
            return e
    return None


def delete_event(user_id: int, event_id: int) -> bool:
    events = _load(user_id)
    new = [e for e in events if e["id"] != event_id]
    if len(new) == len(events):
        return False
    _save(user_id, new)
    return True
