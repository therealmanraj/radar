"""
diagnose_sensors.py
-------------------
Run this (with the server stopped) to see exactly what devices are visible.

    python diagnose_sensors.py
"""

print("=" * 60)
print("BGT60TR13C SENSOR DIAGNOSTIC")
print("=" * 60)

# ── 1. SDK enumeration ────────────────────────────────────────
print("\n[1] ifxradarsdk DeviceFmcw.get_list()")
try:
    from ifxradarsdk.fmcw import DeviceFmcw
    uuids = DeviceFmcw.get_list()
    print(f"    Devices found: {len(uuids)}")
    for i, uid in enumerate(uuids):
        print(f"      [{i}]  UUID = {uid!r}")
    if len(uuids) == 0:
        print("    !! No devices — check USB cables and driver")
    elif len(uuids) == 1:
        print("    !! Only 1 device — second board may not be connected / powered")
except Exception as e:
    print(f"    ERROR: {e}")

# ── 2. USB device list (Windows WMIC) ─────────────────────────
print("\n[2] USB devices matching VID 058B (Infineon)")
try:
    import subprocess
    out = subprocess.check_output(
        ["wmic", "path", "Win32_USBControllerDevice", "get", "Dependent"],
        text=True, stderr=subprocess.DEVNULL
    )
    # Also try the PnPEntity path for friendly names
    out2 = subprocess.check_output(
        ["wmic", "path", "Win32_PnPEntity", "where",
         "DeviceID like '%VID_058B%'",
         "get", "DeviceID,Name"],
        text=True, stderr=subprocess.DEVNULL
    )
    lines = [l.strip() for l in out2.splitlines() if "058B" in l]
    if lines:
        for l in lines:
            print(f"      {l}")
    else:
        print("      (none found via WMIC)")
except Exception as e:
    print(f"    WMIC not available or error: {e}")

# ── 3. pyserial list_ports ────────────────────────────────────
print("\n[3] pyserial list_ports (all ports)")
try:
    from serial.tools import list_ports
    ports = list(list_ports.comports())
    if not ports:
        print("    (no serial/COM ports found)")
    for p in ports:
        print(f"      {p.device:10s}  hwid={p.hwid!r}  desc={p.description!r}")
    ifx = [p for p in ports if "058B" in (p.hwid or "") or "IFX" in (p.description or "").upper()]
    print(f"\n    Infineon-matched ports: {len(ifx)}")
    for p in ifx:
        print(f"      >> {p.device}  {p.description}")
except Exception as e:
    print(f"    ERROR: {e}")

# ── 4. Try opening each UUID ──────────────────────────────────
print("\n[4] Attempting to open each SDK UUID")
try:
    from ifxradarsdk.fmcw import DeviceFmcw
    uuids = DeviceFmcw.get_list()
    for uid in uuids:
        print(f"\n    Opening UUID {uid!r} ...", end=" ", flush=True)
        try:
            dev = DeviceFmcw(uuid=uid)
            frame = dev.get_next_frame()
            shape = frame[0].shape
            dev._close()
            print(f"OK  frame shape={shape}")
        except Exception as e:
            print(f"FAILED: {e}")
except Exception as e:
    print(f"    ERROR: {e}")

print("\n" + "=" * 60)
print("DIAGNOSIS COMPLETE")
print("=" * 60)
