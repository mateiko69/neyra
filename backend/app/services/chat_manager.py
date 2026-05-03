import asyncio
import logging
from collections import defaultdict

from fastapi import WebSocket

log = logging.getLogger(__name__)

_APP_LOOP: asyncio.AbstractEventLoop | None = None


def set_app_event_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    global _APP_LOOP
    _APP_LOOP = loop


def schedule_ws_send_to_user(user_id: int, payload: dict) -> None:
    """Fire-and-forget WS delivery from a sync/background thread (e.g. demo behavior tick)."""
    if _APP_LOOP is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(manager.send_to_user(int(user_id), payload), _APP_LOOP)
    except Exception:
        log.debug("schedule_ws_send_to_user failed", exc_info=True)


class ConnectionManager:
    def __init__(self):
        self.active = defaultdict(list)

    async def connect(self, user_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active[user_id].append(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket):
        if user_id in self.active and websocket in self.active[user_id]:
            self.active[user_id].remove(websocket)

    async def send_to_user(self, user_id: int, payload: dict):
        for ws in self.active.get(user_id, []):
            await ws.send_json(payload)

manager = ConnectionManager()
