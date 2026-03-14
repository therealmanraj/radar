"""
server/app.py
-------------
FastAPI application — dual-sensor radar dashboard.

Endpoints
---------
GET  /device/status                — detect both boards, report running state
POST /device/connect/{sensor_id}   — start reader thread for sensor 0 or 1
POST /device/disconnect/{sensor_id}— stop reader thread for sensor 0 or 1

WS   /ws/{sensor_id}              — frame stream for sensor 0 or 1
GET  /config                       — current server config

Each sensor has an independent:
  - ConnectionManager  (WebSocket clients)
  - asyncio.Queue      (maxsize=1, drops stale frames)
  - radar reader thread
  - stop event

To swap data source:  change _build_source() — one place, nothing else changes.
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
NUM_SENSORS = 2

CONFIG: dict = {
    "source":      "sdk",          # "simulation" | "sdk"
    "num_range":   32,             # NUM_SAMPLES // 2 = 32 range bins
    "num_doppler": 64,             # NUM_CHIRPS = 64 with board default config
    "fps":         20,
    "log_scale":   True,
}

# ---------------------------------------------------------------------------
# Per-sensor mutable state  (only touched from event loop via thread-safe APIs)
# ---------------------------------------------------------------------------
managers: list[ConnectionManager]          = [ConnectionManager() for _ in range(NUM_SENSORS)]
_queues:  list[asyncio.Queue | None]       = [None] * NUM_SENSORS
_threads: list[threading.Thread | None]    = [None] * NUM_SENSORS
_stops:   list[threading.Event]            = [threading.Event() for _ in range(NUM_SENSORS)]
_event_loop: asyncio.AbstractEventLoop | None = None


# ---------------------------------------------------------------------------
# Device detection  (blocking — run in executor so it never stalls the loop)
# ---------------------------------------------------------------------------
def _detect_all() -> list[dict]:
    """
    Return a list of NUM_SENSORS device dicts, one per slot.
    Uses SDK enumeration first (most reliable for USB bulk-transfer devices).
    VID: 058B  PID: 0251  keyword: IFX
    """
    result: list[dict] = [
        {"detected": False, "uuid": None, "description": "No BGT60TR13C found"}
        for _ in range(NUM_SENSORS)
    ]

    # 1. SDK enumeration — returns list of UUID strings
    try:
        from ifxradarsdk.fmcw import DeviceFmcw
        uuids = DeviceFmcw.get_list()
        logger.info("SDK found %d device(s): %s", len(uuids), uuids)
        for i, uid in enumerate(uuids[:NUM_SENSORS]):
            result[i] = {
                "detected":    True,
                "uuid":        uid,
                "description": f"BGT60TR13C  (…{uid[-8:]})",
            }
    except Exception as exc:
        logger.warning("SDK device scan failed: %s", exc)

    # 2. Pyserial fallback — catches boards visible as CDC serial ports
    #    Gives detected=True without a UUID; connect will open first available board.
    if not any(r["detected"] for r in result):
        try:
            from serial.tools import list_ports
            ifx_ports = [
                p for p in list_ports.comports()
                if ("058B" in (p.hwid or "") and "0251" in (p.hwid or ""))
                or "IFX" in (p.description or "").upper()
                or "BGT60" in (p.description or "").upper()
            ]
            logger.info("Pyserial fallback found %d port(s)", len(ifx_ports))
            for i, port in enumerate(ifx_ports[:NUM_SENSORS]):
                result[i] = {
                    "detected":    True,
                    "uuid":        None,   # will open first available board
                    "description": f"BGT60TR13C  ({port.device})",
                }
        except Exception as exc:
            logger.warning("Pyserial fallback failed: %s", exc)

    # 4. Simulation fallback — mark all slots as "detected"
    if CONFIG["source"] == "simulation":
        for i in range(NUM_SENSORS):
            if not result[i]["detected"]:
                result[i] = {
                    "detected":    True,
                    "uuid":        f"SIM-{i}",
                    "description": f"Simulation {i} — no physical device",
                }

    return result


# ---------------------------------------------------------------------------
# Radar source factory
# ---------------------------------------------------------------------------
def _build_source(uuid: str | None):
    if CONFIG["source"] == "simulation" or (uuid and uuid.startswith("SIM")):
        return SimulatedRadar(CONFIG["num_range"], CONFIG["num_doppler"])
    return InfineonRadar(uuid=uuid)


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
            zero_vel_row = display.shape[0] // 2
            motion_mask  = display.copy()
            motion_mask[zero_vel_row - 4 : zero_vel_row + 5, :] = display.min()
            motion_idx   = np.unravel_index(motion_mask.argmax(), motion_mask.shape)

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
# Async broadcast loop  (one per sensor, runs for lifetime of server)
# ---------------------------------------------------------------------------
async def _broadcast_loop(manager: ConnectionManager, queue: asyncio.Queue) -> None:
    while True:
        payload = await queue.get()
        if manager.count > 0:
            await manager.broadcast_json(payload)


# ---------------------------------------------------------------------------
# App lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _event_loop
    _event_loop = asyncio.get_event_loop()
    for i in range(NUM_SENSORS):
        _queues[i] = asyncio.Queue(maxsize=1)
        asyncio.create_task(_broadcast_loop(managers[i], _queues[i]))
    logger.info("Server ready — open http://localhost:8000")
    yield
    # Daemon threads die with the process


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Radar Dashboard", lifespan=lifespan)


@app.get("/config")
async def get_config() -> dict:
    return CONFIG


@app.get("/device/status")
async def device_status() -> dict:
    devices = await asyncio.get_event_loop().run_in_executor(None, _detect_all)
    return {
        "sensors": [
            {
                **devices[i],
                "connected": _threads[i] is not None and _threads[i].is_alive(),
                "clients":   managers[i].count,
            }
            for i in range(NUM_SENSORS)
        ]
    }


@app.post("/device/connect/{sensor_id}")
async def device_connect(sensor_id: int) -> dict:
    if sensor_id not in range(NUM_SENSORS):
        return {"ok": False, "error": "Invalid sensor ID"}
    if _threads[sensor_id] and _threads[sensor_id].is_alive():
        return {"ok": False, "error": "Already running"}

    devices = await asyncio.get_event_loop().run_in_executor(None, _detect_all)
    if not devices[sensor_id]["detected"]:
        return {"ok": False, "error": f"No device found for sensor {sensor_id}"}

    uuid   = devices[sensor_id]["uuid"]
    source = _build_source(uuid)

    _stops[sensor_id] = threading.Event()
    _threads[sensor_id] = threading.Thread(
        target=_radar_reader,
        args=(
            source, CONFIG["fps"], _queues[sensor_id],
            _event_loop, _stops[sensor_id], CONFIG["log_scale"],
        ),
        daemon=True,
        name=f"radar-reader-{sensor_id}",
    )
    _threads[sensor_id].start()
    logger.info("Sensor %d reader started.", sensor_id)
    return {"ok": True}


@app.post("/device/disconnect/{sensor_id}")
async def device_disconnect(sensor_id: int) -> dict:
    if sensor_id not in range(NUM_SENSORS):
        return {"ok": False, "error": "Invalid sensor ID"}
    _stops[sensor_id].set()
    _threads[sensor_id] = None
    logger.info("Sensor %d stop requested.", sensor_id)
    return {"ok": True}


@app.websocket("/ws/{sensor_id}")
async def websocket_endpoint(ws: WebSocket, sensor_id: int) -> None:
    if sensor_id not in range(NUM_SENSORS):
        await ws.close(code=1008)
        return
    await managers[sensor_id].connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        managers[sensor_id].disconnect(ws)


# Static files — always last
app.mount("/", StaticFiles(directory="static", html=True), name="static")
