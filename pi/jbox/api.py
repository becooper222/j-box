"""Client for the task-manager J-Box device API.

All network errors are swallowed and logged: the box must keep working
(showing the archive it already has) when the WiFi hiccups.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests

log = logging.getLogger("jbox.api")

CACHE_FILE = Path(__file__).resolve().parent.parent / "messages.cache.json"


@dataclass
class Message:
    id: str
    body: str
    occasion: str | None
    created_at: str
    read_at: str | None
    hearted_at: str | None

    @property
    def is_unread(self) -> bool:
        return self.read_at is None

    def created_date_text(self) -> str:
        try:
            dt = datetime.fromisoformat(self.created_at.replace("Z", "+00:00")).astimezone()
            return dt.strftime("%b %d, %Y")
        except ValueError:
            return self.created_at[:10]


class JBoxAPI:
    def __init__(self, base_url: str, token: str):
        self._url = f"{base_url}/api/jbox/device"
        self._headers = {"Authorization": f"Bearer {token}"}
        self._lock = threading.Lock()
        self.messages: list[Message] = self._load_cache()
        self.online = False

    # -- polling ---------------------------------------------------------

    def poll(self) -> bool:
        """Fetch latest messages. Returns True if anything changed."""
        try:
            res = requests.get(self._url, headers=self._headers, timeout=15)
            res.raise_for_status()
            rows = res.json()
        except (requests.RequestException, ValueError) as e:
            log.warning("poll failed: %s", e)
            self.online = False
            return False

        self.online = True
        fresh = [
            Message(
                id=r["id"],
                body=r["body"],
                occasion=r.get("occasion"),
                created_at=r["created_at"],
                read_at=r.get("read_at"),
                hearted_at=r.get("hearted_at"),
            )
            for r in rows
        ]
        with self._lock:
            changed = [ (m.id, m.read_at) for m in fresh ] != [ (m.id, m.read_at) for m in self.messages ]
            self.messages = fresh
        if changed:
            self._save_cache()

        undelivered = [r["id"] for r in rows if not r.get("delivered_at")]
        if undelivered:
            self._mark("delivered", undelivered)
        return changed

    def snapshot(self) -> list[Message]:
        with self._lock:
            return list(self.messages)

    def unread(self) -> list[Message]:
        return [m for m in self.snapshot() if m.is_unread]

    # -- actions ---------------------------------------------------------

    def mark_read(self, message_id: str) -> None:
        # Optimistic local update so the UI never re-reveals a read note offline.
        now = datetime.now().astimezone().isoformat()
        with self._lock:
            for m in self.messages:
                if m.id == message_id:
                    m.read_at = m.read_at or now
        self._save_cache()
        threading.Thread(target=self._mark, args=("read", [message_id]), daemon=True).start()

    def mark_hearted(self, message_id: str) -> None:
        now = datetime.now().astimezone().isoformat()
        with self._lock:
            for m in self.messages:
                if m.id == message_id:
                    m.hearted_at = m.hearted_at or now
        self._save_cache()
        threading.Thread(target=self._mark, args=("heart", [message_id]), daemon=True).start()

    def _mark(self, action: str, ids: list[str]) -> None:
        try:
            requests.post(
                self._url,
                headers=self._headers,
                json={"action": action, "ids": ids},
                timeout=15,
            ).raise_for_status()
        except requests.RequestException as e:
            log.warning("mark %s failed: %s", action, e)

    # -- offline cache ----------------------------------------------------

    def _load_cache(self) -> list[Message]:
        try:
            rows = json.loads(CACHE_FILE.read_text())
            return [Message(**r) for r in rows]
        except (OSError, ValueError, TypeError):
            return []

    def _save_cache(self) -> None:
        try:
            with self._lock:
                rows = [vars(m) for m in self.messages]
            CACHE_FILE.write_text(json.dumps(rows, indent=1))
        except OSError as e:
            log.warning("cache write failed: %s", e)
