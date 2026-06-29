"""Tracks active WebSocket clients and broadcasts market snapshots."""

from __future__ import annotations

import asyncio
import logging
from typing import List

from fastapi import WebSocket

logger = logging.getLogger("market.ws")


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: List[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.append(websocket)
        logger.info("WebSocket connected (%d active)", len(self._connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)
        logger.info("WebSocket disconnected (%d active)", len(self._connections))

    async def broadcast(self, message: dict) -> None:
        """Send ``message`` (as JSON) to every connected client.

        Dead connections are pruned rather than allowed to raise.
        """
        async with self._lock:
            targets = list(self._connections)
        stale: List[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(message)
            except Exception:
                stale.append(ws)
        if stale:
            async with self._lock:
                for ws in stale:
                    if ws in self._connections:
                        self._connections.remove(ws)
