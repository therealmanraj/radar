"""
server/broadcast.py
-------------------
WebSocket connection manager.
Keeps track of all connected browser clients and fans out frames to all of them.
"""

from __future__ import annotations

import logging
from typing import Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Thread-safe* broadcast hub for WebSocket clients.

    *All methods are called from async context (the event-loop thread),
    so no extra locking is needed.
    """

    def __init__(self) -> None:
        self._connections: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)
        logger.info("Client connected  — total: %d", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)
        logger.info("Client disconnected — total: %d", len(self._connections))

    async def broadcast_json(self, data: dict) -> None:
        """Send JSON payload to every connected client. Dead sockets are pruned."""
        dead: Set[WebSocket] = set()
        for ws in self._connections:
            try:
                await ws.send_json(data)
            except Exception:
                dead.add(ws)
        self._connections -= dead

    # ------------------------------------------------------------------ #
    # Future upgrade point: swap broadcast_json → broadcast_bytes
    # and send raw Float32Array for Canvas renderer (zero JSON overhead).
    #
    # async def broadcast_bytes(self, data: bytes) -> None:
    #     dead = set()
    #     for ws in self._connections:
    #         try:
    #             await ws.send_bytes(data)
    #         except Exception:
    #             dead.add(ws)
    #     self._connections -= dead
    # ------------------------------------------------------------------ #

    @property
    def count(self) -> int:
        return len(self._connections)
