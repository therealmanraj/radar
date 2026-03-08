"""
detect_ports.py
---------------
Lists all serial ports on macOS and highlights the Infineon BGT60TR13C
by its known VID:PID (058B:0251).

Run: python detect_ports.py
"""

import serial.tools.list_ports

# Known Infineon USB identifiers
INFINEON_VID = "058B"
INFINEON_PID = "0251"
INFINEON_DESC_KEYWORD = "IFX"


def list_all_ports():
    ports = list(serial.tools.list_ports.comports())

    if not ports:
        print("[!] No serial devices found. Is the board plugged in?")
        return []

    print(f"[+] Found {len(ports)} serial port(s):\n")
    found_infineon = []

    for p in ports:
        hwid = p.hwid or ""
        desc = p.description or ""

        is_infineon = (
            INFINEON_VID in hwid.upper()
            and INFINEON_PID in hwid.upper()
        ) or INFINEON_DESC_KEYWORD in desc.upper()

        tag = "  <-- INFINEON BGT60TR13C DETECTED" if is_infineon else ""

        print(f"  Device     : {p.device}")
        print(f"  Name       : {p.name}")
        print(f"  Description: {desc}")
        print(f"  HWID       : {hwid}{tag}")
        print("-" * 55)

        if is_infineon:
            found_infineon.append(p.device)

    if found_infineon:
        print(f"\n[OK] Infineon device(s) found at: {found_infineon}")
    else:
        print("\n[!] No Infineon device matched VID:PID 058B:0251 or 'IFX' description.")
        print("    Try: replug the board, or check 'system_profiler SPUSBDataType' manually.")

    return found_infineon


if __name__ == "__main__":
    list_all_ports()
