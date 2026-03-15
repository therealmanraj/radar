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

Detection strategy (same proven logic as single-sensor, extended for N boards):
  1. SDK DeviceFmcw.get_list() — most reliable for USB bulk-transfer devices
  2. pyserial list_ports fallback — boards enumerated as CDC serial
  3. Simulation fallback — when CONFIG["source"] == "simulation"
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
    "source":      "sdk",   # "simulation" | "sdk"
    "num_range":   32,      # NUM_SAMPLES // 2
    "num_doppler": 64,      # NUM_CHIRPS (board default)
    "fps":         20,
    "log_scale":   True,
}

# ---------------------------------------------------------------------------
# Per-sensor mutable state
# ---------------------------------------------------------------------------
managers: list[ConnectionManager]       = [ConnectionManager() for _ in range(NUM_SENSORS)]
_queues:  list[asyncio.Queue | None]    = [None] * NUM_SENSORS
_threads: list[threading.Thread | None] = [None] * NUM_SENSORS
_stops:   list[threading.Event]         = [threading.Event() for _ in range(NUM_SENSORS)]
_event_loop: asyncio.AbstractEventLoop | None = None

# Cache last-seen device info so connect doesn't re-scan (already-open devices
# disappear from get_list(), which would make sensor 1 un-connectable after
# sensor 0 is already open).
_device_cache: list[dict] = [
    {"detected": False, "uuid": None, "description": "No BGT60TR13C found"}
    for _ in range(NUM_SENSORS)
]


# ---------------------------------------------------------------------------
# Device detection
# ---------------------------------------------------------------------------
def _detect_all() -> list[dict]:
    """
    Return a list of exactly NUM_SENSORS dicts, one per sensor slot.
    Uses the same proven detection logic as the original single-sensor code,
    extended to enumerate multiple boards.
    """
    result: list[dict] = [
        {"detected": False, "uuid": None, "description": "No BGT60TR13C found"}
        for _ in range(NUM_SENSORS)
    ]

    # 1. SDK enumeration — most reliable for USB bulk-transfer devices
    try:
        from ifxradarsdk.fmcw import DeviceFmcw
        uuids = DeviceFmcw.get_list()
        logger.info("SDK found %d device(s)", len(uuids))
        for i, uid in enumerate(uuids[:NUM_SENSORS]):
            result[i] = {
                "detected":    True,
                "uuid":        uid,
                "description": f"BGT60TR13C  (…{uid[-8:]})",
            }
        if uuids:
            return result   # SDK found at least one — trust it completely
    except Exception as exc:
        logger.warning("SDK device scan failed: %s", exc)

    # 2. pyserial fallback — boards that enumerate as CDC serial on some drivers
    try:
        from serial.tools import list_ports
        ifx_ports = [
            p for p in list_ports.comports()
            if ("058B" in (p.hwid or "") and "0251" in (p.hwid or ""))
            or "IFX"   in (p.description or "").upper()
            or "BGT60" in (p.description or "").upper()
        ]
        logger.info("pyserial fallback found %d port(s)", len(ifx_ports))
        for i, port in enumerate(ifx_ports[:NUM_SENSORS]):
            result[i] = {
                "detected":    True,
                "uuid":        None,   # open first-available board on connect
                "description": f"BGT60TR13C  ({port.device})",
            }
    except Exception as exc:
        logger.warning("pyserial fallback failed: %s", exc)

    # 3. Simulation fallback
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
# Source factory
# ---------------------------------------------------------------------------
def _build_source(uuid: str | None):
    if CONFIG["source"] == "simulation" or (uuid and uuid.startswith("SIM")):
        return SimulatedRadar(CONFIG["num_range"], CONFIG["num_doppler"])
    return InfineonRadar(uuid=uuid)


# ---------------------------------------------------------------------------
# Thread-safe frame delivery
# ---------------------------------------------------------------------------
def _enqueue_latest(queue: asyncio.Queue, payload: dict) -> None:
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

            peak_idx     = np.unravel_index(display.argmax(), display.shape)
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
# Async broadcast loop — one per sensor
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


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Radar Dashboard", lifespan=lifespan)


@app.get("/config")
async def get_config() -> dict:
    return CONFIG


@app.get("/device/status")
async def device_status() -> dict:
    global _device_cache
    devices = await asyncio.get_event_loop().run_in_executor(None, _detect_all)
    # Update cache per slot:
    # - Skip slots that are actively streaming: their DeviceFmcw is already open
    #   so get_list() hides it, shifting every subsequent UUID one index earlier.
    #   Trusting the shifted list would corrupt the UUID stored for that slot.
    # - For idle slots: update only when positively detected; keep a previously
    #   seen UUID rather than clearing it on a scan that found fewer devices.
    for i in range(NUM_SENSORS):
        if _threads[i] is not None and _threads[i].is_alive():
            continue  # slot is live — don't touch its cached UUID
        if devices[i]["detected"]:
            _device_cache[i] = devices[i]
        elif not _device_cache[i]["detected"]:
            _device_cache[i] = devices[i]   # still not detected — update normally
    return {
        "sensors": [
            {
                **_device_cache[i],
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

    if not _device_cache[sensor_id]["detected"]:
        return {"ok": False, "error": f"No device detected for sensor {sensor_id}"}

    source = _build_source(_device_cache[sensor_id]["uuid"])
    _stops[sensor_id] = threading.Event()
    _threads[sensor_id] = threading.Thread(
        target=_radar_reader,
        args=(source, CONFIG["fps"], _queues[sensor_id],
              _event_loop, _stops[sensor_id], CONFIG["log_scale"]),
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
