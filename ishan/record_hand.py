"""
STEP 1 — Record Both Signatures (Single Session)
=================================================
Records hand AND empty signatures in one run — radar stays connected throughout.

Instructions:
  1. Place hand ~30-50cm in front of radar
  2. Run this script
  3. Follow the prompts

Output files:
  hand_signature.npy
  empty_signature.npy

Run:
    python record_signature.py
"""

import numpy as np
from scipy.signal import windows
from ifxradarsdk.fmcw import DeviceFmcw
import time
import os

# ─────────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────────
RECORD_FRAMES = 60    # Frames to average per recording
WARMUP_FRAMES = 10    # Discard first N frames (radar settling)


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def drain_buffer(device, n=5):
    for _ in range(n):
        try:
            device.get_next_frame()
        except Exception:
            pass


def compute_range_profile(chirp_data: np.ndarray) -> np.ndarray:
    """Range profile magnitude averaged across chirps. Returns (num_range_bins,)"""
    num_chirps, num_samples = chirp_data.shape
    win       = windows.hann(num_samples)
    range_fft = np.fft.fft(chirp_data * win[np.newaxis, :], axis=1)
    magnitude = np.abs(range_fft[:, :num_samples // 2])
    return magnitude.mean(axis=0)


def record_signature(device, label) -> np.ndarray:
    """
    Record RECORD_FRAMES frames and average into a stable signature.
    Returns array of shape (num_rx, num_range_bins)
    """
    drain_buffer(device, 5)

    # Warmup
    print(f"  Warming up...", end="", flush=True)
    for _ in range(WARMUP_FRAMES):
        try:
            device.get_next_frame()
            time.sleep(0.05)
        except Exception:
            pass
    print(" done.")

    # Record
    print(f"  Recording {RECORD_FRAMES} frames", end="", flush=True)
    profiles = []

    for _ in range(RECORD_FRAMES):
        try:
            drain_buffer(device, 2)
            frame  = device.get_next_frame()[0]   # (num_rx, num_chirps, num_samples)
            num_rx = frame.shape[0]

            frame_profiles = []
            for rx in range(num_rx):
                rp = compute_range_profile(frame[rx])
                frame_profiles.append(rp)

            profiles.append(np.array(frame_profiles))
            print(".", end="", flush=True)
            time.sleep(0.05)

        except Exception:
            print("x", end="", flush=True)

    print(" done.")

    if not profiles:
        raise RuntimeError("No frames recorded — check radar connection.")

    signature = np.mean(profiles, axis=0)   # (num_rx, num_range_bins)
    print(f"  Shape: {signature.shape}  |  Max: {signature.max():.4f}\n")
    return signature


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    print("=" * 50)
    print("  RADAR SIGNATURE RECORDER")
    print("=" * 50)
    print()

    print("Connecting to radar...")
    with DeviceFmcw() as device:
        print("Connected!\n")

        # ── STEP 1: Record hand ──────────────────────
        print("─" * 40)
        print("RECORDING 1 of 2 — Hand")
        print("─" * 40)
        print("Place the Hand ~30–50cm directly")
        print("in front of the radar and keep it still.")
        print()
        input("Press Enter when ready...")
        print()

        hand_sig = record_signature(device, "hand")
        np.save("hand_signature.npy", hand_sig)
        print(f"✅ Saved: {os.path.abspath('hand_signature.npy')}\n")

        # ── STEP 2: Record empty ────────────────────
        print("─" * 40)
        print("RECORDING 2 of 2 — Empty Scene")
        print("─" * 40)
        print("Remove the hand. Make sure nothing is")
        print("in front of the radar.")
        print()
        input("Press Enter when ready...")
        print()

        empty_sig = record_signature(device, "empty")
        np.save("empty_signature.npy", empty_sig)
        print(f"✅ Saved: {os.path.abspath('empty_signature.npy')}\n")

    # ── Done ────────────────────────────────────
    print("=" * 50)
    print("  Both signatures recorded successfully!")
    print("=" * 50)
    print()
    print("Next step — run the detector:")
    print("  python detect_hand.py")
    print()


if __name__ == "__main__":
    main()