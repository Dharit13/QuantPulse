"""WebSocket connection manager with Redis pub/sub for cross-service events.

The API service subscribes to Redis channels and broadcasts to connected
WebSocket clients. The Worker service publishes events when regime changes,
new signals are generated, or pipeline status updates occur.
"""

import asyncio
import json
import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger(__name__)

CHANNELS = ("ws:regime", "ws:signals", "ws:pipeline")


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._subscriptions: dict[str, set[WebSocket]] = defaultdict(set)
        self._pubsub_task: asyncio.Task | None = None

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)
        for channel in CHANNELS:
            self._subscriptions[channel].add(websocket)
        logger.info("WebSocket client connected (%d total)", len(self._connections))

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)
        for subs in self._subscriptions.values():
            subs.discard(websocket)
        logger.info("WebSocket client disconnected (%d remaining)", len(self._connections))

    async def broadcast(self, channel: str, data: dict) -> None:
        message = json.dumps({"channel": channel.replace("ws:", ""), **data})
        dead: list[WebSocket] = []
        for ws in self._subscriptions.get(channel, set()):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def start_redis_listener(self) -> None:
        """Subscribe to Redis pub/sub channels and broadcast to WebSocket clients."""
        from backend.redis_client import get_redis

        r = get_redis()
        if r is None:
            logger.info("Redis unavailable — WebSocket will work without cross-service events")
            return

        self._pubsub_task = asyncio.create_task(self._listen_redis(r))

    async def _listen_redis(self, r) -> None:
        """Long-running loop that reads from Redis pub/sub."""
        try:
            pubsub = r.pubsub()
            pubsub.subscribe(*CHANNELS)
            logger.info("Redis pub/sub listener started on channels: %s", CHANNELS)

            while True:
                msg = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                )
                if msg and msg["type"] == "message":
                    channel = msg["channel"]
                    try:
                        data = json.loads(msg["data"])
                    except (json.JSONDecodeError, TypeError):
                        data = {"raw": str(msg["data"])}
                    await self.broadcast(channel, data)
                else:
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.info("Redis pub/sub listener cancelled")
        except Exception as e:
            logger.warning("Redis pub/sub listener error: %s", e)

    async def shutdown(self) -> None:
        if self._pubsub_task:
            self._pubsub_task.cancel()
            try:
                await self._pubsub_task
            except asyncio.CancelledError:
                pass

    @property
    def client_count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


def publish_event(channel: str, event: str, data: dict) -> None:
    """Publish an event to Redis pub/sub (called from Worker or background tasks).

    This is synchronous and safe to call from scheduler jobs or threads.
    """
    from backend.redis_client import get_redis

    r = get_redis()
    if r is None:
        return

    payload = json.dumps({"event": event, "data": data})
    try:
        r.publish(channel, payload)
    except Exception as e:
        logger.debug("Redis publish failed on %s: %s", channel, e)
