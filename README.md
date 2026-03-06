# BGT60TR13C Radar — Python Acquisition + Streamlit Heatmap

Infineon DEMO BGT60TR13C | 60 GHz FMCW | Python 3 | Windows

---

## Project goal

```
BGT60TR13C sensor
      │  USB
      ▼
  Python acquisition (ifxradarsdk)
      │  numpy arrays  (num_rx × num_chirps × num_samples)
      ▼
  DSP processing (FFT → Range-Doppler map)
      │  2D power matrix
      ▼
  Streamlit GUI → live heatmap
```

---

## Current status

| Component | Status |
|---|---|
| Board detected | **COM3** — VID:PID=058B:0251 (BGT60TR13C) |
| ifxradarsdk | **3.6.4** — installed from `radar_sdk.zip` |
| Frame capture | Working — 10 frames verified |
| Streamlit GUI | Working — Real SDK mode functional |

---

## Key hardware fact (read this first)

The BGT60TR13C exposes **two separate USB interfaces** on the same cable:

| Interface | What it is | How to access |
|---|---|---|
| IFX CDC (`COMx` on Windows) | Control/status channel | pyserial — but you will see **zero bytes** here (normal) |
| USB Bulk endpoint | Actual radar frame data | **ifxradarsdk only** — pyserial cannot see this |

**Conclusion:** pyserial can open the port and confirm the board is alive, but it will never receive radar frames. The SDK connects via USB bulk transfer — no COM port needed.

---

## LED blink guide

| LED pattern | Meaning |
|---|---|
| Steady green | Normal — idle or measuring |
| Fast green blink | Firmware running, actively acquiring |
| Slow green blink | Bootloader / waiting for firmware flash |
| No light | Power issue, bad cable, or board not detected |

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
├── usb_check.py           ← query OS USB tree (Windows: PowerShell/PnP)
│
├── sdk_check.py           ← verify ifxradarsdk installation
├── avian_test.py          ← SDK frame capture (--sim mode works without hardware)
│
└── app.py                 ← Streamlit heatmap GUI (real SDK + simulation modes)
```

---

## Setup (Windows)

### 1. Install the Radar Development Kit

The RDK installer places the SDK at:

```
C:\Infineon\Tools\Radar-Development-Kit\3.6.5\assets\software\radar_sdk.zip
```

The Python wheel is bundled inside that zip. Extract and install it into your venv:

```python
# extract_and_install.py does this automatically:
python extract_and_install.py
```

Or manually:

```cmd
# Extract the wheel from the zip, then:
.venv\Scripts\python.exe -m pip install ifxradarsdk-3.6.4+4b4a6245-py3-none-win_amd64.whl
```

### 2. Install other dependencies

```cmd
.venv\Scripts\python.exe -m pip install pyserial numpy streamlit matplotlib
```

### 3. Verify everything

```cmd
.venv\Scripts\python.exe sdk_check.py
```

Expected output:

```
[OK] ifxradarsdk                    — version: unknown
[OK] ifxradarsdk.fmcw               — version: unknown
[OK] ifxAvian                       — version: unknown
[OK] numpy — 2.4.2
[OK] matplotlib — ...
[OK] streamlit — ...
[OK] serial — ...
```

---

## Running

### Board detection

```cmd
.venv\Scripts\python.exe detect_ports.py
```

Expected:
```
  Device     : COM3
  HWID       : USB VID:PID=058B:0251 ...  <-- INFINEON BGT60TR13C DETECTED
```

### Frame capture (CLI)

```cmd
.venv\Scripts\python.exe avian_test.py              # real hardware
.venv\Scripts\python.exe avian_test.py --sim        # simulation, no hardware needed
.venv\Scripts\python.exe avian_test.py --frames 50  # capture 50 frames
```

Real hardware output:
```
[OK] Device found!
     Sensor: BGT60TR13C FMCW Radar Sensor
[*] Capturing 10 frames...
  Frame 000:  RX0: peak@bin0=1.529  RX1: peak@bin0=1.686  RX2: peak@bin0=0.495
  ...
[OK] Capture complete.
```

### Streamlit heatmap GUI

```cmd
.venv\Scripts\python.exe -m streamlit run app.py
```

Opens at `http://localhost:8501`

In the sidebar, select **Real SDK (ifxradarsdk)** then click **Start**.

---

## SDK frame format

`device.get_next_frame()` returns:

```python
frame = device.get_next_frame()
# frame: list of length 1
# frame[0]: numpy array, shape (num_rx=3, num_chirps=32, num_samples=64)

rx_data = frame[0]          # (3, 32, 64)
rx0     = rx_data[0]        # (32, 64) — RX antenna 0
```

### Range-Doppler map (as used in app.py)

```python
win_range   = np.hanning(rx0.shape[1])
win_doppler = np.hanning(rx0.shape[0])
windowed    = rx0 * win_range[np.newaxis, :] * win_doppler[:, np.newaxis]

range_fft = np.fft.fft(windowed, axis=1)[:, :rx0.shape[1] // 2]   # one-sided
rd_map    = np.fft.fftshift(np.fft.fft(range_fft, axis=0), axes=0) # centred Doppler
power     = np.abs(rd_map)  # shape: (32, 32)
```

---

## BGT60TR13C technical reference

| Parameter | Value |
|---|---|
| Frequency | 57–64 GHz (configured: 60–61.5 GHz) |
| Range resolution | ~10 cm (depends on bandwidth) |
| Max range (DEMO) | ~3–5 m |
| RX antennas | 3 |
| TX antennas | 1 |
| USB VID:PID | 058B:0251 |
| CDC port (Windows) | COM3 (may vary) |
| Data interface | USB Bulk (NOT CDC serial) |
| SDK package | ifxradarsdk 3.6.4 |
| SDK source | `C:\Infineon\...\radar_sdk.zip` → `python_wheels\` |

---

## Troubleshooting

### Board not detected at all
- Use a data USB cable (not charge-only)
- Try a different USB port (avoid hubs)
- Power-cycle the board after plugging in

### SDK says "device not found"
- WinUSB driver not installed — re-run the RDK installer and allow driver install
- Another process holds the device — close Radar Fusion GUI before running Python
- Board connected via hub — try direct connection

### Zero bytes from pyserial
- Expected. The BGT60TR13C sends radar data over USB bulk transfer, not CDC serial. Use the SDK.

### Peak always at bin 0
- Normal for an empty room — bin 0 is DC/LO leakage. Place an object in front of the sensor to see a peak at a higher range bin.

### Streamlit heatmap looks wrong
- `rx_mask=7` uses all 3 RX antennas; `app.py` currently uses RX0 only for the map
- Range FFT output shape is `(num_chirps, num_samples // 2)` — one-sided

---

## Quick command reference

```cmd
# Diagnosis
.venv\Scripts\python.exe test.py
.venv\Scripts\python.exe detect_ports.py
.venv\Scripts\python.exe usb_check.py

# SDK
.venv\Scripts\python.exe sdk_check.py
.venv\Scripts\python.exe avian_test.py --sim
.venv\Scripts\python.exe avian_test.py

# GUI
.venv\Scripts\python.exe -m streamlit run app.py
```
