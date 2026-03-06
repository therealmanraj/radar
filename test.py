"""
test.py
-------
Master diagnostic script for the Infineon BGT60TR13C DEMO board on macOS.
Runs all checks in sequence:
  1. List serial ports and identify Infineon device
  2. Open the IFX CDC port and inspect raw bytes
  3. Query USB tree via system_profiler
  4. Check SDK availability
  5. Print a hardware troubleshooting checklist

Run: python test.py
"""

import serial
import serial.tools.list_ports
import subprocess
import importlib
import time
import sys

# ---- Configuration ----
# Auto-set fallback port based on OS; auto-detection always runs first
KNOWN_PORT = "COM3" if sys.platform == "win32" else "/dev/cu.usbmodem1301"
BAUD_RATE    = 115200
READ_SEC     = 3        # seconds to listen for bytes on the serial port

INFINEON_VID = "058B"
INFINEON_PID = "0251"


# ============================
# STEP 1: List serial ports
# ============================
def step_list_ports():
    print("\n" + "=" * 60)
    print("STEP 1 — Serial port scan")
    print("=" * 60)

    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("[!] No serial ports found. Board may not be connected.")
        return None

    target_port = None
    for p in ports:
        hwid = (p.hwid or "").upper()
        desc = (p.description or "")
        is_ifx = (INFINEON_VID in hwid and INFINEON_PID in hwid) or "IFX" in desc.upper()
        marker = " <-- INFINEON (IFX CDC)" if is_ifx else ""
        print(f"  {p.device}  |  {desc}  |  {hwid}{marker}")
        if is_ifx:
            target_port = p.device

    if target_port:
        print(f"\n[OK] Infineon device at: {target_port}")
    else:
        print(f"\n[?] No VID:PID 058B:0251 match. Trying configured port: {KNOWN_PORT}")
        target_port = KNOWN_PORT

    return target_port


# ============================
# STEP 2: Open port + inspect bytes
# ============================
def step_inspect_port(port: str):
    print("\n" + "=" * 60)
    print(f"STEP 2 — Open and inspect: {port}")
    print("=" * 60)

    try:
        ser = serial.Serial(port, BAUD_RATE, timeout=0.5)
        print(f"[OK] Port opened: {ser.name} @ {BAUD_RATE} baud")
    except serial.SerialException as e:
        print(f"[!] Cannot open port: {e}")
        print("    Is another app (Radar Fusion GUI, screen) holding the port?")
        return

    # Let firmware settle after port open
    time.sleep(1.0)

    # Try sending a bare CR/LF to trigger any command prompt
    try:
        ser.write(b"\r\n")
    except Exception:
        pass

    # Collect bytes for READ_SEC seconds
    print(f"[*] Listening for {READ_SEC}s...")
    collected = b""
    deadline = time.time() + READ_SEC
    while time.time() < deadline:
        n = ser.in_waiting
        if n:
            chunk = ser.read(n)
            collected += chunk
            print(f"  [>] {n} bytes: {chunk[:80]!r}")
        else:
            time.sleep(0.1)

    ser.close()

    # Analysis
    print()
    if collected:
        print(f"[OK] Received {len(collected)} bytes total.")
        printable = sum(1 for b in collected if 32 <= b < 127) / len(collected)
        if printable > 0.7:
            print(f"     Looks like ASCII/text: {collected.decode('ascii', errors='replace')[:200]}")
        else:
            print(f"     Looks like binary data. Hex: {collected[:32].hex()}")
    else:
        print("[?] Zero bytes received.")
        print()
        print("    This is expected if:")
        print("    a) The CDC port is a CONTROL interface — real data goes over")
        print("       USB bulk transfers, accessible only via ifxradarsdk, NOT pyserial.")
        print("    b) The firmware is in bootloader mode (fast LED blink).")
        print()
        print("    Key insight: BGT60TR13C sends radar frames via USB bulk transfer,")
        print("    not via the CDC serial stream. pyserial can open the port but")
        print("    will see nothing. You need the Infineon SDK to get frame data.")


# ============================
# STEP 3: USB device tree
# ============================
def step_usb_check():
    print("\n" + "=" * 60)
    print("STEP 3 — macOS USB device tree check")
    print("=" * 60)

    try:
        result = subprocess.run(
            ["system_profiler", "SPUSBDataType"],
            capture_output=True, text=True, timeout=15
        )
        output = result.stdout
    except Exception as e:
        print(f"[!] system_profiler failed: {e}")
        return

    # Search for Infineon entries
    found_lines = [l for l in output.splitlines()
                   if "058b" in l.lower() or "ifx" in l.upper() or "0251" in l.lower()]

    if found_lines:
        print("[OK] Infineon USB entry found in system_profiler output:")
        for l in found_lines:
            print(f"  {l.strip()}")
    else:
        print("[!] Infineon device not found in USB tree.")
        print("    Run: system_profiler SPUSBDataType | grep -i 'ifx\\|058b'")


# ============================
# STEP 4: SDK check
# ============================
def step_sdk_check():
    print("\n" + "=" * 60)
    print("STEP 4 — Infineon SDK / package availability")
    print("=" * 60)

    packages = [
        ("ifxradarsdk",      "Infineon Radar SDK"),
        ("ifxradarsdk.fmcw", "FMCW submodule"),
        ("numpy",            "numpy"),
        ("streamlit",        "streamlit"),
        ("matplotlib",       "matplotlib"),
    ]

    for pkg, label in packages:
        try:
            mod = importlib.import_module(pkg)
            v = getattr(mod, "__version__", "installed")
            print(f"  [OK] {label:<25} {v}")
        except ImportError:
            status = "MISSING — pip install ifxradarsdk" if "ifx" in pkg else f"MISSING — pip install {pkg}"
            print(f"  [--] {label:<25} {status}")


# ============================
# STEP 5: Hardware checklist
# ============================
def step_checklist():
    print("\n" + "=" * 60)
    print("STEP 5 — Hardware troubleshooting checklist")
    print("=" * 60)

    checklist = [
        ("LED state",
         "Steady green = good. Fast blink = bootloader/error.\n"
         "         Fast blink fix: reflash firmware via Radar Fusion GUI."),
        ("Shield seating",
         "Power off. Remove the BGT60TR13C shield. Re-press firmly onto\n"
         "         the baseboard headers. All pins must be seated."),
        ("USB cable",
         "Must be a data cable (not charge-only). Try a different cable\n"
         "         and a different USB port. Avoid USB hubs."),
        ("macOS USB-C hub",
         "Some hubs block CDC devices. Connect directly to the Mac."),
        ("Port conflict",
         "Close Radar Fusion GUI, Arduino IDE, screen, or any other app\n"
         "         that may hold /dev/cu.usbmodem1301 open."),
        ("Firmware",
         "If LED fast-blinks: open Radar Fusion GUI (from Infineon RDK),\n"
         "         let it detect and flash/update the firmware automatically."),
        ("SDK path",
         "install ifxradarsdk from Infineon's website wheel file,\n"
         "         then run avian_test.py to confirm end-to-end."),
    ]

    for i, (title, detail) in enumerate(checklist, 1):
        print(f"  {i}. [{title}] {detail}")

    print()
    print("Next scripts to run:")
    print("  python detect_ports.py   — confirm port detection")
    print("  python inspect_serial.py — multi-baud deep scan + byte log")
    print("  python usb_check.py      — full USB tree dump")
    print("  python sdk_check.py      — verify SDK install")
    print("  python avian_test.py     — test SDK (--sim flag for no hardware)")
    print("  streamlit run app.py     — launch heatmap GUI")


# ============================
# MAIN
# ============================
if __name__ == "__main__":
    print("=" * 60)
    print("BGT60TR13C Master Diagnostic — test.py")
    print(f"Python {sys.version}")
    print("=" * 60)

    port = step_list_ports()

    if port:
        step_inspect_port(port)

    step_usb_check()
    step_sdk_check()
    step_checklist()

    print("\n[Done] Diagnostic complete.")
