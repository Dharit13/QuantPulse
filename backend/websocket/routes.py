"""WebSocket endpoint for real-time push of regime, signals, and pipeline events."""

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.websocket.manager import manager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)

    try:
        from backend.data.cache import data_cache

        regime = data_cache.get("pipeline:regime")
        if regime:
            await websocket.send_text(
                json.dumps(
                    {
                        "channel": "regime",
                        "event": "current_state",
                        "data": regime,
                    }
                )
            )
    except Exception:
        pass

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                action = msg.get("action")

                if action == "ping":
                    await websocket.send_text(json.dumps({"channel": "system", "event": "pong"}))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
