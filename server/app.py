"""
server/app.py
-------------
FastAPI application.

Architecture:
  [radar reader thread]  →  asyncio.Queue(maxsize=1)  →  [broadcast coroutine]  →  WebSocket clients

The radar SDK is blocking, so it runs in a daemon thread.
`loop.call_soon_threadsafe` is the ONLY safe way to hand data from that
thread into the async event loop — no other synchronisation primitives needed.

To switch data source:
  Uncomment the InfineonRadar import and swap the `source = ...` line.
  Nothing else changes.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from radar.simulation import SimulatedRadar
# from radar.sdk import InfineonRadar          # ← swap here for real device
from server.broadcast import ConnectionManager

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared state (written once at startup, read-only after that)
# ---------------------------------------------------------------------------
CONFIG: dict = {
    "source": "simulation",   # "simulation" | "sdk"
    "num_range": 64,
    "num_doppler": 32,
    "fps": 20,
    "log_scale": True,
}

manager = ConnectionManager()
_frame_queue: asyncio.Queue = None   # type: ignore[assignment]
_event_loop: asyncio.AbstractEventLoop = None   # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Thread-safe frame delivery
# ---------------------------------------------------------------------------
def _enqueue_latest(queue: asyncio.Queue, payload: dict) -> None:
    """
    Always keep only the NEWEST frame in the queue.
    Old frames are dropped so the browser never falls behind.
    Runs inside the event loop (scheduled via call_soon_threadsafe).
    """
    if queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    try:
        queue.put_nowait(payload)
    except asyncio.QueueFull:
        pass   # extremely unlikely race — skip silently


# ---------------------------------------------------------------------------
# Radar reader thread
# ---------------------------------------------------------------------------
def _radar_reader(
    source,
    fps: float,
    queue: asyncio.Queue,
    loop: asyncio.AbstractEventLoop,
    log_scale: bool,
) -> None:
    """
    Blocking loop that reads frames from the radar source and pushes them
    into the async queue via the event loop.
    Runs as a daemon thread — dies automatically when the process exits.
    """
    frame_index = 0
    frame_delay = 1.0 / fps

    with source:
        logger.info("Radar reader thread started  fps=%s  source=%s", fps, type(source).__name__)
        while True:
            t0 = time.perf_counter()

            raw = source.get_frame()   # shape: (num_doppler, num_range)

            if log_scale:
                display = 20.0 * np.log10(np.clip(raw, 1e-6, None))
            else:
                display = raw

            peak_idx = np.unravel_index(display.argmax(), display.shape)

            payload = {
                "z": display.tolist(),
                "meta": {
                    "frame": frame_index,
                    "rows": display.shape[0],
                    "cols": display.shape[1],
                    "peak": float(display.max()),
                    "peak_range_bin": int(peak_idx[1]),
                    "peak_doppler_bin": int(peak_idx[0]),
                    "log_scale": log_scale,
                },
            }

            # Hand off to the event loop — never blocks the thread
            loop.call_soon_threadsafe(_enqueue_latest, queue, payload)

            frame_index += 1
            elapsed = time.perf_counter() - t0
            sleep_s = frame_delay - elapsed
            if sleep_s > 0:
                time.sleep(sleep_s)


# ---------------------------------------------------------------------------
# Async broadcast loop
# ---------------------------------------------------------------------------
async def _broadcast_loop(queue: asyncio.Queue) -> None:
    """Reads frames from the queue and broadcasts to all WebSocket clients."""
    while True:
        payload = await queue.get()
        if manager.count > 0:
            await manager.broadcast_json(payload)


# ---------------------------------------------------------------------------
# App lifespan  (startup + shutdown)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _frame_queue, _event_loop

    _event_loop = asyncio.get_event_loop()
    _frame_queue = asyncio.Queue(maxsize=1)   # drop stale frames, never backlog

    # ── Pick data source ──────────────────────────────────────────────────
    source = SimulatedRadar(CONFIG["num_range"], CONFIG["num_doppler"])
    # source = InfineonRadar(CONFIG["num_range"], CONFIG["num_doppler"])  # real device

    # ── Start radar reader thread ─────────────────────────────────────────
    thread = threading.Thread(
        target=_radar_reader,
        args=(source, CONFIG["fps"], _frame_queue, _event_loop, CONFIG["log_scale"]),
        daemon=True,
        name="radar-reader",
    )
    thread.start()

    # ── Start async broadcaster ───────────────────────────────────────────
    asyncio.create_task(_broadcast_loop(_frame_queue))

    logger.info("Server ready — open http://localhost:8000")
    yield
    # Daemon thread is killed automatically on process exit


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Radar Dashboard", lifespan=lifespan)


@app.get("/config")
async def get_config() -> dict:
    """Frontend fetches this on load to initialise the renderer."""
    return CONFIG


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()   # keep-alive / ignore client messages
    except WebSocketDisconnect:
        manager.disconnect(ws)


# ---------------------------------------------------------------------------
# Static files — mount LAST so API routes always win
# ---------------------------------------------------------------------------
app.mount("/", StaticFiles(directory="static", html=True), name="static")
