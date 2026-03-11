"""
server/app.py
-------------
FastAPI application — step-by-step radar connection flow.

Endpoints
---------
GET  /device/status      — detect Infineon board + report running state
POST /device/connect     — start radar reader thread + broadcaster
POST /device/disconnect  — signal thread to stop

WS   /ws                 — frame stream (active only while connected)
GET  /config             — current server config

Radar thread lifecycle
----------------------
Thread does NOT start at server boot.  It only starts when the frontend
calls POST /device/connect, and stops on POST /device/disconnect.
The thread checks `_stop_event` each loop iteration so it exits cleanly.

To swap data source:
  Change the `_build_source()` function — one place, nothing else changes.
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
from radar.sdk import InfineonRadar
from server.broadcast import ConnectionManager

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CONFIG: dict = {
    "source":      "sdk",          # "simulation" | "sdk"
    "num_range":   32,             # NUM_SAMPLES // 2 = 32 range bins
    "num_doppler": 64,             # NUM_CHIRPS = 64 with board default config
    "fps":         20,
    "log_scale":   True,
}

# ---------------------------------------------------------------------------
# Mutable runtime state  (only touched from the event loop via thread-safe APIs)
# ---------------------------------------------------------------------------
manager      = ConnectionManager()
_frame_queue: asyncio.Queue | None         = None
_event_loop:  asyncio.AbstractEventLoop | None = None
_radar_thread: threading.Thread | None     = None
_stop_event:   threading.Event             = threading.Event()


# ---------------------------------------------------------------------------
# Device detection  (blocking — run in executor so it never stalls the loop)
# ---------------------------------------------------------------------------
def _detect_device() -> dict:
    """
    Detect the BGT60TR13C eval board.

    IMPORTANT: the board communicates via USB bulk transfers, NOT CDC serial.
    pyserial list_ports will usually NOT find it.
    The correct approach is to ask the SDK to enumerate devices first.

    VID: 058B  PID: 0251  (from old/detect_ports.py)
    Description keyword: 'IFX'  (not 'INFINEON')
    """

    # 1. Try SDK enumeration first — most reliable for bulk-transfer devices
    try:
        from ifxradarsdk.fmcw import DeviceFmcw
        ids = DeviceFmcw.get_list()   # list of serial-number strings; empty = no device
        if ids:
            return {
                "detected":    True,
                "port":        None,
                "description": f"BGT60TR13C  (SDK serial: {ids[0]})",
            }
    except Exception as exc:
        logger.debug("SDK device scan: %s", exc)

    # 2. Fallback: check serial/USB-serial ports with correct VID:PID + keyword
    #    (catches boards that enumerate as CDC on some Windows driver combos)
    try:
        from serial.tools import list_ports
        for port in list_ports.comports():
            hwid = (port.hwid        or "").upper()
            desc = (port.description or "").upper()
            # VID=058B, PID=0251, or description contains 'IFX' (Infineon prefix)
            if ("058B" in hwid and "0251" in hwid) or "IFX" in desc or "BGT60" in desc:
                return {
                    "detected":    True,
                    "port":        port.device,
                    "description": port.description,
                }
    except Exception as exc:
        logger.debug("list_ports scan: %s", exc)

    # 3. Simulation mode — always report "detected" so the UI is usable without hardware
    if CONFIG["source"] == "simulation":
        return {
            "detected":    True,
            "port":        "SIM",
            "description": "Simulation — no physical device required",
        }

    return {"detected": False, "port": None, "description": "No BGT60TR13C found"}


# ---------------------------------------------------------------------------
# Radar source factory — swap here for real device
# ---------------------------------------------------------------------------
def _build_source():
    if CONFIG["source"] == "simulation":
        return SimulatedRadar(CONFIG["num_range"], CONFIG["num_doppler"])
    if CONFIG["source"] == "sdk":
        return InfineonRadar()
    raise ValueError(f"Unknown source: {CONFIG['source']}")


# ---------------------------------------------------------------------------
# Thread-safe frame delivery
# ---------------------------------------------------------------------------
def _enqueue_latest(queue: asyncio.Queue, payload: dict) -> None:
    """Drop stale frame if queue is full, keep only the newest."""
    if queue.full():
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
    try:
        queue.put_nowait(payload)
    except asyncio.QueueFull:
        pass


# ---------------------------------------------------------------------------
# Radar reader thread
# ---------------------------------------------------------------------------
def _radar_reader(
    source,
    fps: float,
    queue: asyncio.Queue,
    loop: asyncio.AbstractEventLoop,
    stop_event: threading.Event,
    log_scale: bool,
) -> None:
    frame_index = 0
    frame_delay = 1.0 / fps

    with source:
        logger.info("Radar reader started  fps=%s  source=%s", fps, type(source).__name__)
        while not stop_event.is_set():
            t0 = time.perf_counter()

            raw     = source.get_frame()
            display = 20.0 * np.log10(np.clip(raw, 1e-6, None)) if log_scale else raw

            # ── Global peak (includes static clutter) ────────────────────────
            peak_idx = np.unravel_index(display.argmax(), display.shape)

            # ── Motion peak — mask ±4 doppler bins around zero-velocity ──────
            # Shape is (num_doppler, num_range).  After fftshift, zero-velocity
            # is at row  num_doppler // 2.  Masking it reveals the moving-target
            # peak which is what matters for hand detection at 30 cm.
            zero_vel_row  = display.shape[0] // 2
            motion_mask   = display.copy()
            motion_mask[zero_vel_row - 4 : zero_vel_row + 5, :] = display.min()
            motion_idx    = np.unravel_index(motion_mask.argmax(), motion_mask.shape)

            payload = {
                "z": display.tolist(),
                "meta": {
                    "frame":              frame_index,
                    "rows":               display.shape[0],
                    "cols":               display.shape[1],
                    "peak":               float(display.max()),
                    "peak_range_bin":     int(peak_idx[1]),
                    "peak_doppler_bin":   int(peak_idx[0]),
                    "motion_peak":        float(motion_mask.max()),
                    "motion_range_bin":   int(motion_idx[1]),
                    "motion_doppler_bin": int(motion_idx[0]),
                    "log_scale":          log_scale,
                },
            }

            loop.call_soon_threadsafe(_enqueue_latest, queue, payload)
            frame_index += 1

            elapsed = time.perf_counter() - t0
            sleep_s = frame_delay - elapsed
            if sleep_s > 0:
                time.sleep(sleep_s)

    logger.info("Radar reader stopped.")


# ---------------------------------------------------------------------------
# Async broadcast loop  (runs for the lifetime of the server)
# ---------------------------------------------------------------------------
async def _broadcast_loop(queue: asyncio.Queue) -> None:
    while True:
        payload = await queue.get()
        if manager.count > 0:
            await manager.broadcast_json(payload)


# ---------------------------------------------------------------------------
# App lifespan  — only set up the queue + broadcaster, NOT the radar thread
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _frame_queue, _event_loop
    _event_loop  = asyncio.get_event_loop()
    _frame_queue = asyncio.Queue(maxsize=1)
    asyncio.create_task(_broadcast_loop(_frame_queue))
    logger.info("Server ready — open http://localhost:8000")
    yield
    # Daemon thread dies with the process


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Radar Dashboard", lifespan=lifespan)


@app.get("/config")
async def get_config() -> dict:
    return CONFIG


@app.get("/device/status")
async def device_status() -> dict:
    running = _radar_thread is not None and _radar_thread.is_alive()
    detection = await asyncio.get_event_loop().run_in_executor(None, _detect_device)
    return {
        **detection,
        "connected": running,
        "clients":   manager.count,
    }


@app.post("/device/connect")
async def device_connect() -> dict:
    global _radar_thread, _stop_event

    if _radar_thread and _radar_thread.is_alive():
        return {"ok": False, "error": "Already running"}

    _stop_event = threading.Event()
    source      = _build_source()

    _radar_thread = threading.Thread(
        target=_radar_reader,
        args=(source, CONFIG["fps"], _frame_queue, _event_loop, _stop_event, CONFIG["log_scale"]),
        daemon=True,
        name="radar-reader",
    )
    _radar_thread.start()
    logger.info("Radar thread started by client request.")
    return {"ok": True}


@app.post("/device/disconnect")
async def device_disconnect() -> dict:
    global _radar_thread
    if _stop_event:
        _stop_event.set()
    _radar_thread = None
    logger.info("Radar thread stop requested.")
    return {"ok": True}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)


# Static files — always last
app.mount("/", StaticFiles(directory="static", html=True), name="static")
