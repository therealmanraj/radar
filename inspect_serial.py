"""
inspect_serial.py
-----------------
Opens the Infineon IFX CDC serial port and performs a deep inspection:
  - Tries to read raw bytes for several seconds
  - Tries common baud rates
  - Attempts basic probe commands
  - Logs all raw bytes to a file for offline analysis

The BGT60TR13C DEMO board exposes a USB CDC port. This port may be:
  (a) A control/command interface (ASCII or binary protocol)
  (b) A raw data stream (binary frames)
  (c) A bootloader interface (if firmware is not yet flashed)

Fast-blinking green LED meanings:
  - Steady green  -> normal operation, measurement running
  - Fast blink    -> firmware starting, bootloader mode, or error state
  - No light      -> power issue or board not detected

Run: python inspect_serial.py
"""

import serial
import serial.tools.list_ports
import time
import os

# --- Configuration ---
# Default fallback port — auto-detection runs first (see auto_detect_port below)
import sys as _sys
PORT = "COM3" if _sys.platform == "win32" else "/dev/cu.usbmodem1301"
BAUD_RATES = [115200, 921600, 2000000, 9600, 57600]
READ_DURATION_SEC = 5              # How long to listen per baud rate
LOG_FILE = "raw_serial_log.bin"    # Binary dump of received bytes

# Common probe commands (ASCII) some Infineon firmware accepts
PROBE_COMMANDS = [
    b"\r\n",           # just CR/LF to wake up
    b"AT\r\n",         # generic AT command
    b"?\r\n",          # help
    b"version\r\n",    # version query
    b"start\r\n",      # start measurement
]


def auto_detect_port() -> str:
    """Try to auto-detect the Infineon port if the configured one is missing."""
    for p in serial.tools.list_ports.comports():
        hwid = (p.hwid or "").upper()
        desc = (p.description or "").upper()
        if "058B" in hwid or "IFX" in desc:
            print(f"[*] Auto-detected Infineon port: {p.device}")
            return p.device
    return PORT  # fall back to configured port


def try_baud_rate(port: str, baud: int) -> bytes:
    """
    Open port at given baud rate, send probe commands, and collect all bytes
    received within READ_DURATION_SEC seconds.
    Returns the raw bytes received.
    """
    received = b""
    try:
        ser = serial.Serial(
            port=port,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.5,         # short read timeout
            write_timeout=1.0,
        )
        print(f"  [+] Opened {port} @ {baud} baud")
        time.sleep(0.3)          # let the port settle

        # Send each probe command
        for cmd in PROBE_COMMANDS:
            try:
                ser.write(cmd)
            except Exception:
                pass
            time.sleep(0.05)

        # Read for READ_DURATION_SEC seconds
        deadline = time.time() + READ_DURATION_SEC
        while time.time() < deadline:
            waiting = ser.in_waiting
            if waiting:
                chunk = ser.read(waiting)
                received += chunk
                print(f"  [>] {len(chunk)} bytes received: {chunk[:64]!r}")
            else:
                time.sleep(0.1)

        ser.close()

    except serial.SerialException as e:
        print(f"  [!] Could not open at {baud}: {e}")

    return received


def log_bytes(data: bytes, path: str):
    """Append raw bytes to a log file."""
    with open(path, "ab") as f:
        f.write(data)
    print(f"  [*] Logged {len(data)} bytes to {path}")


def analyse_bytes(data: bytes):
    """Quick analysis of received bytes."""
    if not data:
        print("  [=] No bytes received at this baud rate.")
        return

    printable = sum(1 for b in data if 32 <= b < 127)
    ratio = printable / len(data)
    print(f"  [=] Total bytes: {len(data)}")
    print(f"  [=] Printable ratio: {ratio:.1%} ({'likely ASCII/text' if ratio > 0.7 else 'likely binary data'})")

    # Try decoding as ASCII if mostly printable
    if ratio > 0.7:
        try:
            print(f"  [=] Decoded text: {data.decode('ascii', errors='replace')[:200]}")
        except Exception:
            pass
    else:
        print(f"  [=] Hex preview: {data[:32].hex()}")


def main():
    print("=" * 60)
    print("Infineon BGT60TR13C Serial Port Inspector")
    print("=" * 60)

    port = auto_detect_port()
    print(f"\n[*] Target port: {port}")
    print(f"[*] Read duration per baud rate: {READ_DURATION_SEC}s")
    print(f"[*] Log file: {os.path.abspath(LOG_FILE)}\n")

    # Clear log file
    open(LOG_FILE, "wb").close()

    all_data = b""
    for baud in BAUD_RATES:
        print(f"\n--- Testing baud rate: {baud} ---")
        data = try_baud_rate(port, baud)
        analyse_bytes(data)
        if data:
            log_bytes(data, LOG_FILE)
            all_data += data
            # If we got a clear response, stop trying other baud rates
            if len(data) > 10:
                print(f"\n[OK] Got meaningful data at {baud} baud. Stopping baud scan.")
                break

    print("\n" + "=" * 60)
    if all_data:
        print(f"[OK] Total data collected: {len(all_data)} bytes")
        print("[*] Check raw_serial_log.bin for full binary dump")
    else:
        print("[!] No data received on any baud rate.")
        print()
        print("What this means:")
        print("  1. The IFX CDC port may be a CONTROL interface only —")
        print("     actual radar data comes via a different USB endpoint")
        print("     (bulk transfer, not CDC serial). In that case, you")
        print("     MUST use the Infineon SDK / ifxradarsdk, not pyserial.")
        print()
        print("  2. The firmware may not be running (fast LED blink =")
        print("     bootloader mode). You may need to flash firmware via")
        print("     Infineon RDK tools first.")
        print()
        print("  3. The shield may not be seated correctly on the baseboard.")
        print("     Power off, remove, reattach the BGT60TR13C shield firmly.")
        print()
        print("Next step: run sdk_check.py to see if ifxradarsdk is available.")
    print("=" * 60)


if __name__ == "__main__":
    main()
