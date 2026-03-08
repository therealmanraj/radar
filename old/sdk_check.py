"""
sdk_check.py
------------
Checks which Infineon radar SDK components are available in the current
Python environment, and prints installation instructions if missing.

The BGT60TR13C is supported by Infineon's RDK3 (Radar Development Kit 3).
The Python wrapper package is: ifxradarsdk

Run: python sdk_check.py
"""

import sys
import importlib

PACKAGES = [
    ("ifxradarsdk",        "Top-level Infineon Radar SDK"),
    ("ifxradarsdk.fmcw",   "FMCW radar module (BGT60TR13C uses FMCW)"),
    ("ifxAvian",           "Alternative Avian module name (older SDK versions)"),
    ("ifxDopplerLFM",      "Doppler LFM processing module"),
]


def check_package(module_name: str, description: str):
    try:
        mod = importlib.import_module(module_name)
        version = getattr(mod, "__version__", "unknown")
        print(f"  [OK] {module_name:<30} ({description}) — version: {version}")
        return True
    except ImportError as e:
        print(f"  [--] {module_name:<30} ({description}) — NOT FOUND: {e}")
        return False


def main():
    print("=" * 65)
    print("Infineon Radar SDK Availability Check")
    print(f"Python: {sys.version}")
    print(f"Executable: {sys.executable}")
    print("=" * 65)
    print()

    results = {}
    for pkg, desc in PACKAGES:
        results[pkg] = check_package(pkg, desc)

    print()
    sdk_ok = results.get("ifxradarsdk", False) or results.get("ifxAvian", False)

    if sdk_ok:
        print("[OK] Infineon radar SDK is available. Run avian_test.py next.")
    else:
        print("[!] Infineon SDK not found. Installation options:")
        print()
        print("  Option A — pip install (if available for your Python version):")
        print("    pip install ifxradarsdk")
        print()
        print("  Option B — Download from Infineon (recommended):")
        print("    1. Go to: https://www.infineon.com/cms/en/product/sensor/radar-sensors/")
        print("       (search for BGT60TR13C -> Software & Tools -> RDK)")
        print("    2. Download 'Radar SDK' for your OS (macOS arm64 or x86_64)")
        print("    3. Install the .whl file:")
        print("       pip install ifxradarsdk-*.whl")
        print()
        print("  Option C — Use the Radar Fusion GUI:")
        print("    Infineon provides a standalone GUI that does not need Python SDK.")
        print("    It is the quickest way to verify the hardware is working.")
        print()
        print("  NOTE: Without the SDK, pyserial alone cannot read radar frames.")
        print("  The BGT60TR13C sends data over USB bulk transfers, not CDC serial.")

    print()
    print("Also checking standard scientific packages:")
    for pkg in ["numpy", "matplotlib", "streamlit", "serial"]:
        try:
            mod = importlib.import_module(pkg)
            v = getattr(mod, "__version__", "ok")
            print(f"  [OK] {pkg} — {v}")
        except ImportError:
            print(f"  [--] {pkg} — pip install {pkg}")


if __name__ == "__main__":
    main()
