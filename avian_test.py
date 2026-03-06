"""
avian_test.py
-------------
Attempts to connect to the BGT60TR13C using the Infineon ifxradarsdk
and reads a few radar frames, printing basic info.

If the SDK is not installed, runs in SIMULATION mode with random data
so you can see what the data pipeline looks like.

Run: python avian_test.py
     python avian_test.py --sim   # force simulation mode

The SDK uses USB bulk transfers (NOT serial). It finds the device by
VID:PID automatically — you do not need to specify a serial port.
"""

import sys
import argparse
import time
import numpy as np

# --- Parse arguments ---
parser = argparse.ArgumentParser()
parser.add_argument("--sim", action="store_true", help="Force simulation mode (no hardware needed)")
parser.add_argument("--frames", type=int, default=10, help="Number of frames to capture (default: 10)")
args = parser.parse_args()

SIMULATE = args.sim

# --- Try to import Infineon SDK ---
SDK_AVAILABLE = False
if not SIMULATE:
    try:
        import ifxradarsdk
        from ifxradarsdk.fmcw import DeviceFmcw
        from ifxradarsdk.fmcw.types import FmcwSimpleSequenceConfig, FmcwSequenceChirp
        SDK_AVAILABLE = True
        print(f"[OK] ifxradarsdk loaded — version {getattr(ifxradarsdk, '__version__', '3.6.4')}")
    except ImportError:
        print("[!] ifxradarsdk not found — falling back to SIMULATION mode.")
        print("    Install the SDK and re-run without --sim for real data.\n")
        SIMULATE = True


# -----------------------------------------------------------------------
# Simulation helper: generate fake radar frames that mimic the SDK output
# -----------------------------------------------------------------------
def generate_simulated_frame(num_rx: int = 3, num_chirps: int = 32, num_samples: int = 64) -> list:
    """
    Returns a list of numpy arrays (one per RX antenna), each shaped
    (num_chirps, num_samples) with complex float32 values.
    This matches the real SDK frame format.
    """
    frames = []
    for _ in range(num_rx):
        # Simulate some range peaks + Doppler spread + noise
        data = np.random.randn(num_chirps, num_samples).astype(np.float32) * 0.05
        # Add a synthetic target at range bin 20
        data[:, 20] += np.random.randn(num_chirps) * 0.5 + 1.0
        frames.append(data)
    return frames


# -----------------------------------------------------------------------
# SDK-based acquisition
# -----------------------------------------------------------------------
def run_with_sdk(num_frames: int):
    """Connect to real hardware via SDK and read frames."""
    print("[*] Scanning for BGT60TR13C device via USB...")

    with DeviceFmcw() as device:
        # Print device info
        info = device.get_sensor_information()
        print(f"[OK] Device found!")
        print(f"     Sensor: {info}")

        # Configure a simple FMCW sequence
        # These values work for a basic range measurement
        config = FmcwSimpleSequenceConfig(
            frame_repetition_time_s=0.1,    # 10 fps
            chirp_repetition_time_s=0.5e-3, # chirp interval
            num_chirps=32,
            tdm_mimo=False,
            chirp=FmcwSequenceChirp(
                start_frequency_Hz=60e9,
                end_frequency_Hz=61.5e9,
                sample_rate_Hz=1e6,
                num_samples=64,
                rx_mask=7,   # all 3 RX antennas
                tx_mask=1,
                tx_power_level=31,
                lp_cutoff_Hz=500000,
                hp_cutoff_Hz=80000,
                if_gain_dB=33,
            ),
        )

        sequence = device.create_simple_sequence(config)
        device.set_acquisition_sequence(sequence)

        print(f"\n[*] Capturing {num_frames} frames...\n")

        for i in range(num_frames):
            frame = device.get_next_frame()
            # SDK returns a list of acquisitions; each is (num_rx, num_chirps, num_samples)
            # Split the first acquisition into per-RX arrays for process_frame
            rx_data = frame[0]  # shape: (3, 32, 64)
            rx_arrays = [rx_data[rx] for rx in range(rx_data.shape[0])]
            process_frame(i, rx_arrays)
            time.sleep(0.01)

    print("\n[OK] Capture complete.")


# -----------------------------------------------------------------------
# Frame processing (same for real and simulated data)
# -----------------------------------------------------------------------
def process_frame(frame_idx: int, rx_arrays: list):
    """
    Process one radar frame.
    rx_arrays: list of numpy arrays, one per RX antenna
                shape per antenna: (num_chirps, num_samples)

    For a heatmap, we compute a simple range profile via FFT along samples.
    """
    print(f"  Frame {frame_idx:03d}:", end="")

    range_profiles = []
    for rx_idx, data in enumerate(rx_arrays):
        # Apply Hanning window across samples to reduce sidelobes
        window = np.hanning(data.shape[1])
        windowed = data * window[np.newaxis, :]

        # Range FFT: transform along the sample axis
        range_fft = np.fft.fft(windowed, axis=1)
        range_mag = np.abs(range_fft[:, :data.shape[1] // 2])  # one-sided

        # Average across chirps for a stable range profile
        mean_profile = np.mean(range_mag, axis=0)
        range_profiles.append(mean_profile)

        peak_bin = np.argmax(mean_profile)
        peak_val = mean_profile[peak_bin]
        print(f"  RX{rx_idx}: peak@bin{peak_bin}={peak_val:.3f}", end="")

    print()
    return range_profiles


# -----------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------
def main():
    print("=" * 60)
    print("BGT60TR13C Avian SDK Test")
    print("=" * 60)

    if SIMULATE:
        print("[SIM] Running in simulation mode (no hardware required)\n")
        print(f"[*] Generating {args.frames} simulated frames...\n")

        for i in range(args.frames):
            frame = generate_simulated_frame(num_rx=3, num_chirps=32, num_samples=64)
            process_frame(i, frame)
            time.sleep(0.05)

        print("\n[OK] Simulation complete.")
        print("[*] When SDK is installed, replace generate_simulated_frame()")
        print("    with device.get_next_frame() in run_with_sdk().")
    else:
        run_with_sdk(args.frames)


if __name__ == "__main__":
    main()
