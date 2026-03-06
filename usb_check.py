"""
usb_check.py
------------
Uses macOS system_profiler to find the Infineon BGT60TR13C USB device.
This bypasses pyserial and queries the OS USB stack directly.

Run: python usb_check.py
"""

import subprocess
import sys
import platform


INFINEON_VID = "0x058b"
INFINEON_PID = "0x0251"


def run_system_profiler():
    """Call system_profiler (macOS) and return raw text output."""
    try:
        result = subprocess.run(
            ["system_profiler", "SPUSBDataType"],
            capture_output=True, text=True, timeout=15
        )
        return result.stdout
    except FileNotFoundError:
        print("[!] system_profiler not found — are you on macOS?")
        return ""
    except subprocess.TimeoutExpired:
        print("[!] system_profiler timed out.")
        return ""


def run_windows_usb_check():
    """Use PowerShell to list USB devices on Windows."""
    print("[*] Querying Windows USB device list via PowerShell...")
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "Get-PnpDevice | Where-Object {$_.InstanceId -like '*058B*' -or $_.FriendlyName -like '*IFX*'} | Format-List"],
            capture_output=True, text=True, timeout=20
        )
        output = result.stdout.strip()
        if output:
            print("[OK] Infineon device entry found via PowerShell:\n")
            print(output)
        else:
            print("[?] No Infineon device found via PowerShell.")
            print("    Also try: Device Manager -> View -> Devices by connection")
            print("    Look for 'IFX CDC' or 'BGT60' under USB devices.")
    except FileNotFoundError:
        print("[!] PowerShell not found.")
    except subprocess.TimeoutExpired:
        print("[!] PowerShell query timed out.")


def find_infineon_device(output: str):
    """
    Parse system_profiler output for the Infineon device.
    Looks for VID 058B / PID 0251 in any section.
    """
    lines = output.splitlines()
    found = False
    context_buffer = []

    for i, line in enumerate(lines):
        # Capture a window of context around vendor/product ID matches
        lower = line.lower()
        if "058b" in lower or "ifx" in lower.upper() or "0251" in lower:
            # Print surrounding context (20 lines before/after)
            start = max(0, i - 10)
            end = min(len(lines), i + 10)
            section = lines[start:end]
            context_buffer.append((i, section))
            found = True

    return found, context_buffer


def main():
    if platform.system() == "Windows":
        run_windows_usb_check()
        return

    print("[*] Querying macOS USB device tree via system_profiler...")
    output = run_system_profiler()

    found, contexts = find_infineon_device(output)

    if found:
        print("[OK] Infineon-related USB entry found!\n")
        for line_num, section in contexts:
            print(f"--- Context around line {line_num} ---")
            for l in section:
                print(l)
            print()
    else:
        print("[!] No Infineon device (VID 058B / PID 0251 / 'IFX') found in USB tree.")
        print("    Suggestions:")
        print("    1. Replug the USB cable (use a data cable, not charge-only)")
        print("    2. Try a different USB port")
        print("    3. Check if the shield board is seated properly on the baseboard")
        print("    4. On some macs, USB-C hubs block CDC devices — try direct connection")
        print()

    # Also print full output for manual inspection
    print("=" * 60)
    print("Full system_profiler output (search for '058b' or 'IFX'):")
    print("=" * 60)
    print(output)


if __name__ == "__main__":
    main()
