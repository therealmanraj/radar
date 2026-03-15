# BGT60TR13C Radar Dashboard

Infineon BGT60TR13C | 60 GHz FMCW | Python 3 | Windows

---

## How to run

```bash
pip install -r requirements.txt
pip install ifxradarsdk   # Infineon SDK — see setup below
python main.py
```

Open `http://localhost:8000` in your browser.

---

## Project structure

```
radar/
├── main.py                 ← entry point (run this)
├── requirements.txt
│
├── radar/
│   ├── base.py             ← RadarSource abstract base class
│   ├── sdk.py              ← InfineonRadar — live sensor via ifxradarsdk
│   └── simulation.py       ← SimulatedRadar — fake targets, no hardware needed
│
├── server/
│   ├── app.py              ← FastAPI app (REST + WebSocket endpoints)
│   └── broadcast.py        ← WebSocket connection manager
│
└── static/
    ├── index.html          ← dashboard UI
    └── js/app.js           ← frontend: WebSocket client + heatmap renderer
```

---

## How it works

```
BGT60TR13C board (USB)
      │
      ▼
radar/sdk.py  ←  ifxradarsdk reads raw ADC frames
      │  get_next_frame() → shape (3, 64, 64)
      │  = (num_rx_antennas, num_chirps, num_samples)
      │
      │  DSP pipeline (per frame):
      │    1. MTI clutter filter  — EMA background subtraction
      │    2. Hanning windows     — range axis + Doppler axis
      │    3. Range FFT           — one-sided, 32 bins, 2.5 cm/bin
      │    4. Doppler FFT         — fftshift, zero-velocity at row 32
      │    5. Average magnitude   — across 3 RX antennas
      │
      ▼  (64, 32) float array
server/app.py  ←  radar reader thread
      │  converts to dB, finds peak + motion bin
      │  puts JSON payload into asyncio.Queue
      ▼
server/broadcast.py  ←  WebSocket broadcast to all browser tabs
      │
      ▼
static/js/app.js  ←  renders live Range-Doppler heatmap
```

---

## Sensor physics

| Parameter | Value |
|---|---|
| Frequency sweep | 57–63 GHz (~6 GHz bandwidth) |
| Range resolution | 2.5 cm / bin |
| Range bins | 32 |
| Max range | ~80 cm |
| Doppler bins | 64 |
| Max velocity | ~8.9 km/h (±4.45 km/h) |
| RX antennas | 3 |
| TX antennas | 1 |
| USB VID:PID | 058B:0251 |

---

## Infineon SDK setup (Windows)

1. Download and run the Infineon Radar SDK installer from:
   `https://softwaretools.infineon.com/tools/com.ifx.tb.tool.ifxradarsdk`
2. During install, allow it to install the WinUSB driver (required for bulk-transfer data)
3. Install the Python wheel:
   ```cmd
   pip install <sdk-path>\python\ifxradarsdk-*.whl
   ```
4. Plug in the BGT60TR13C board
5. In Device Manager, confirm the board appears under **Universal Serial Bus devices** (not under Ports)

---

## Simulation mode (no hardware)

To run without a physical sensor, change one line in `server/app.py`:

```python
CONFIG = {
    "source": "simulation",   # was "sdk"
    ...
}
```

Then `python main.py` as normal — the UI will show synthetic targets.

---

## API endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/device/status` | Detect boards, report running state |
| POST | `/device/connect/{sensor_id}` | Start reader thread for sensor 0 or 1 |
| POST | `/device/disconnect/{sensor_id}` | Stop reader thread |
| WS | `/ws/{sensor_id}` | Live frame stream |
| GET | `/config` | Current server config |

Up to 2 boards are supported simultaneously (`sensor_id` = 0 or 1).

---

## Troubleshooting

**SDK says "device not found"**
- WinUSB driver not installed — re-run the SDK installer and choose driver install
- Another app (e.g. Radar Fusion GUI) has the device open — close it first
- Try a direct USB-A port, avoid hubs

**Range reads ~4× too far**
- The bandwidth constant `_BW` in `radar/sdk.py` must match your sensor config.
  Default is `6e9` (6 GHz). If you use a custom JSON config with a narrower sweep, update this value.

**Board not detected at all**
- Use a data cable (not charge-only)
- Power-cycle the board after plugging in
