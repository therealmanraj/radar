# BGT60TR13C Radar — Python Acquisition + Streamlit Heatmap

Infineon DEMO BGT60TR13C | 60 GHz FMCW | Python 3 | macOS / Windows

---

## Project goal

```
BGT60TR13C sensor
      │  USB
      ▼
  Python acquisition (ifxradarsdk)
      │  numpy arrays  (num_chirps × num_samples per RX antenna)
      ▼
  DSP processing (FFT → Range-Doppler map)
      │  2D power matrix
      ▼
  Streamlit GUI → live heatmap
```

---

## Key hardware fact (read this first)

The BGT60TR13C exposes **two separate USB interfaces** on the same cable:

| Interface | What it is | How to access |
|---|---|---|
| IFX CDC (`/dev/cu.usbmodem*` on Mac, `COMx` on Windows) | Control/status channel | pyserial — but you will see **zero bytes** here (normal) |
| USB Bulk endpoint | Actual radar frame data | **ifxradarsdk only** — pyserial cannot see this |

**Conclusion:** pyserial can open the port and confirm the board is alive, but it will never receive radar frames. You need the Infineon SDK for real data.

---

## LED blink guide

| LED pattern | Meaning |
|---|---|
| Steady green | Normal — idle or measuring |
| Fast green blink | Firmware running, actively acquiring |
| Slow green blink | Bootloader / waiting for firmware flash |
| No light | Power issue, bad cable, or board not detected |

Fast blink on macOS is fine — it means the board is alive. The SDK is what unlocks the data.

---

## File map

```
Radar/
├── README.md              ← this file
├── requirements.txt       ← pip dependencies
│
├── test.py                ← MASTER diagnostic (run this first on any machine)
├── detect_ports.py        ← list serial ports, highlight Infineon device
├── inspect_serial.py      ← deep multi-baud scan + raw byte log
├── usb_check.py           ← query OS USB tree (macOS: system_profiler)
│
├── sdk_check.py           ← verify ifxradarsdk installation
├── avian_test.py          ← SDK frame capture (--sim mode works without hardware)
│
└── app.py                 ← Streamlit heatmap GUI
```

---

## Phase 1 — Hardware diagnosis (works on macOS now)

### Install dependencies

```bash
pip install pyserial numpy streamlit matplotlib
```

### Run the master diagnostic

```bash
python test.py
```

Expected output with board connected:
```
STEP 1 — Serial port scan
  /dev/cu.usbmodem1301  |  IFX CDC  |  USB VID:PID=058B:0251  <-- INFINEON

STEP 2 — Open and inspect
  [OK] Port opened @ 115200 baud
  [?]  Zero bytes received  ← NORMAL, see Key hardware fact above

STEP 3 — USB tree check
  [OK] Infineon USB entry found

STEP 4 — SDK check
  [--] ifxradarsdk  MISSING  ← expected on macOS (SDK is Windows-only)
```

### Run individual scripts

```bash
python detect_ports.py     # confirm port is visible
python inspect_serial.py   # multi-baud scan, saves raw_serial_log.bin
python usb_check.py        # full USB tree dump
python sdk_check.py        # check which packages are installed
```

---

## Phase 2 — SDK integration (Windows only)

### Why Windows only?

The Infineon Radar SDK (`ifxradarsdk`) is distributed as a Windows-only installer from:
**https://softwaretools.infineon.com/tools/com.ifx.tb.tool.ifxradarsdk**

It includes:
- `ifxradarsdk` Python wheel (Windows x64)
- USB driver (WinUSB / libusb-win32) — required for the bulk transfer endpoint
- Radar Fusion GUI — a standalone app to verify hardware before writing any code

### Windows setup checklist (do this tomorrow)

```
[ ] 1. Download and run the Infineon Radar SDK installer from the link above
[ ] 2. During install, let it install the USB driver (WinUSB) — required
[ ] 3. Open a cmd/PowerShell and run:
         pip install <path-to-sdk>\python\ifxradarsdk-*.whl
[ ] 4. Plug in the BGT60TR13C board
[ ] 5. Open Device Manager → confirm board appears under "Universal Serial Bus devices"
        (NOT under "Ports (COM & LPT)" — it needs WinUSB, not CDC)
[ ] 6. Run Radar Fusion GUI first to confirm the hardware works end-to-end
[ ] 7. Then run: python sdk_check.py
[ ] 8. Then run: python avian_test.py
[ ] 9. Then run: streamlit run app.py
```

### Install pyserial + other deps on Windows too

```cmd
pip install pyserial numpy streamlit matplotlib
```

### avian_test.py — what it does

```bash
python avian_test.py           # real hardware (SDK required)
python avian_test.py --sim     # simulation mode, no hardware needed
python avian_test.py --frames 50   # capture 50 frames
```

When the SDK is installed and the board is connected it will:
1. Find the device automatically by VID:PID (no COM port needed)
2. Configure a simple FMCW sequence (32 chirps, 64 samples, 60–61.5 GHz)
3. Read N frames and print peak range bin per RX antenna
4. Show how to convert raw ADC data → Range-Doppler map

---

## Phase 3 — Streamlit heatmap GUI

### Run the demo (simulation, works right now on macOS)

```bash
streamlit run app.py
```

Opens in browser at `http://localhost:8501`

### What you see

- A live-updating Range-Doppler heatmap
- Sidebar controls: range bins, doppler bins, FPS, color scale, dB/linear
- Simulated targets moving around — looks exactly like real radar output
- Start/Stop buttons

### Where to plug in real radar data (Phase 2)

In [app.py](app.py), find `get_real_sdk_frame()` — it has a comment block showing exactly what to replace:

```python
# *** PHASE 2: REPLACE THIS WITH REAL SDK CODE ***
# raw_frame = device.get_next_frame()
# rx0 = raw_frame[0]   # shape: (num_chirps, num_samples)
# range_fft = np.fft.fft(rx0, axis=1)[:, :num_samples//2]
# rd_map = np.fft.fftshift(np.fft.fft(range_fft, axis=0), axes=0)
# return np.abs(rd_map)
```

---

## BGT60TR13C technical reference

| Parameter | Value |
|---|---|
| Frequency | 57–64 GHz (typical config: 60–61.5 GHz) |
| Range resolution | ~10 cm (depends on bandwidth) |
| Max range (DEMO) | ~3–5 m |
| RX antennas | 3 |
| TX antennas | 1 |
| USB VID:PID | 058B:0251 |
| CDC port (macOS) | /dev/cu.usbmodem1301 |
| CDC port (Windows) | COMx (varies) |
| Data interface | USB Bulk (NOT CDC serial) |
| SDK package | ifxradarsdk (Windows only) |

---

## Troubleshooting

### Board not detected at all
- Use a data USB cable (not charge-only)
- Try a direct USB-A port (avoid hubs on macOS)
- Power-cycle the board after plugging in

### Port disappears after a few seconds
- Normal if the CDC driver is not loaded — install WinUSB on Windows

### SDK says "device not found"
- WinUSB driver not installed — re-run SDK installer, choose driver install
- Board connected to a hub — try direct connection
- Another process holds the device — close Radar Fusion GUI

### Zero bytes from pyserial
- Expected. See "Key hardware fact" at the top. Use the SDK.

### Streamlit heatmap looks wrong with real data
- Check `rx_mask` in `avian_test.py` — should be 7 (all 3 RX) for BGT60TR13C
- Check `num_samples` matches your config
- Range FFT output shape is `(num_chirps, num_samples // 2)` — one-sided

---

## Quick command reference

```bash
# Diagnosis
python test.py
python detect_ports.py
python inspect_serial.py
python usb_check.py       # macOS only

# SDK
python sdk_check.py
python avian_test.py --sim        # no hardware
python avian_test.py              # real hardware (Windows + SDK)

# GUI
streamlit run app.py
```
