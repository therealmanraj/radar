"""
STEP 2 — Hand Detector
================================
Compares live radar frames against the recorded hand signature.
Shows ONE dot when the hand is detected, nothing otherwise.

Requires:
    hand_signature.npy  — recorded with record_signature.py (choice 1)
    empty_signature.npy     — recorded with record_signature.py (choice 2)

Run:
    python detect_hand.py
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from scipy.signal import windows
from ifxradarsdk.fmcw import DeviceFmcw
import time
import os

# ─────────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────────
HAND_SIG_FILE = "hand_signature.npy"
EMPTY_SIG_FILE    = "empty_signature.npy"

MATCH_THRESHOLD   = 0.75    # 0.0–1.0 — how similar live must be to hand signature
                             # Raise if false positives, Lower if missing detections
MAX_RANGE_M       = 1.0     # Detection range
FOV_DEG           = 120
UPDATE_MS         = 200
SMOOTH_FRAMES     = 5       # Smooth score over N frames to reduce flicker


# ─────────────────────────────────────────────
# SIGNAL PROCESSING
# ─────────────────────────────────────────────
def drain_buffer(device, n=3):
    for _ in range(n):
        try:
            device.get_next_frame()
        except Exception:
            pass


def compute_range_profile(chirp_data: np.ndarray) -> np.ndarray:
    """Range profile magnitude averaged across chirps."""
    num_chirps, num_samples = chirp_data.shape
    win       = windows.hann(num_samples)
    range_fft = np.fft.fft(chirp_data * win[np.newaxis, :], axis=1)
    magnitude = np.abs(range_fft[:, :num_samples // 2])
    return magnitude.mean(axis=0)


def normalise(v: np.ndarray) -> np.ndarray:
    """Normalise vector to unit length for cosine similarity."""
    n = np.linalg.norm(v)
    return v / n if n > 1e-10 else v


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Similarity score 0.0 (completely different) to 1.0 (identical)."""
    return float(np.dot(normalise(a.flatten()), normalise(b.flatten())))


def compute_match_score(live_frame: np.ndarray,
                        hand_sig: np.ndarray,
                        empty_sig: np.ndarray) -> float:
    """
    How much does the live frame look like the hand vs empty scene?

    Returns score 0.0–1.0:
      - Close to 1.0 → hand is present
      - Close to 0.0 → scene is empty or something else
    """
    num_rx = live_frame.shape[0]
    scores = []

    for rx in range(num_rx):
        live_profile  = compute_range_profile(live_frame[rx])

        # Subtract empty background
        hand_profile   = hand_sig[rx]   - empty_sig[rx]
        live_adjusted = live_profile  - empty_sig[rx]

        # Clip negatives (we only care about positive reflections)
        hand_profile   = np.clip(hand_profile,   0, None)
        live_adjusted = np.clip(live_adjusted, 0, None)

        score = cosine_similarity(live_adjusted, hand_profile)
        scores.append(score)

    return float(np.mean(scores))


def estimate_peak_range(live_frame: np.ndarray,
                        empty_sig: np.ndarray,
                        max_range_m: float) -> tuple:
    """
    Find the range bin with strongest reflection above empty background.
    Returns (range_m, angle_deg_approx)
    """
    num_rx, num_chirps, num_samples = live_frame.shape
    num_range_bins = num_samples // 2

    # Use antenna 0 for range
    profile    = compute_range_profile(live_frame[0])
    background = empty_sig[0]
    diff       = np.clip(profile - background, 0, None)

    peak_bin = int(np.argmax(diff))
    range_m  = (peak_bin / num_range_bins) * max_range_m

    # Angle from phase difference between antennas 0 and 1
    try:
        win       = windows.hann(num_samples)
        fft0      = np.fft.fft(live_frame[0] * win[np.newaxis, :], axis=1)
        fft1      = np.fft.fft(live_frame[1] * win[np.newaxis, :], axis=1)
        phase0    = np.angle(fft0[:, peak_bin].mean())
        phase1    = np.angle(fft1[:, peak_bin].mean())
        delta     = (phase1 - phase0 + np.pi) % (2 * np.pi) - np.pi
        angle_deg = np.degrees(np.arcsin(np.clip(delta / np.pi, -1, 1)))
    except Exception:
        angle_deg = 0.0

    return range_m, angle_deg


# ─────────────────────────────────────────────
# LIVE DETECTOR
# ─────────────────────────────────────────────
def run(device, hand_sig, empty_sig):

    print("Draining buffer...", end="", flush=True)
    drain_buffer(device, 10)
    print(" done.\n")
    print(f"Match threshold : {MATCH_THRESHOLD}")
    print(f"Point the radar at the Hand!\n")

    # Get frame shape
    drain_buffer(device, 3)
    frame0 = device.get_next_frame()[0]
    num_rx, num_chirps, num_samples = frame0.shape
    print(f"Frame shape: {frame0.shape}\n")

    # Score history for smoothing
    score_history = []

    # ── Figure ──
    fig = plt.figure(figsize=(9, 8), facecolor="#060610")
    fig.canvas.manager.set_window_title("Hand Detector")
    ax  = fig.add_subplot(111, projection="polar", facecolor="#060610")

    half_fov = np.radians(FOV_DEG / 2)
    ax.set_thetamin(-FOV_DEG / 2)
    ax.set_thetamax(FOV_DEG / 2)
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_ylim(0, MAX_RANGE_M)
    ax.tick_params(colors="#223344")
    ax.yaxis.set_tick_params(labelcolor="#445566", labelsize=8)
    ax.xaxis.set_tick_params(labelcolor="#445566", labelsize=8)
    ax.grid(color="#0d1520", linewidth=0.8, linestyle="--", alpha=0.8)

    theta_fill = np.linspace(-half_fov, half_fov, 100)
    ax.fill_between(theta_fill, 0, MAX_RANGE_M, color="#1a3a5c", alpha=0.15)
    ax.plot([ half_fov,  half_fov], [0, MAX_RANGE_M], color="#2255aa", lw=1, alpha=0.4)
    ax.plot([-half_fov, -half_fov], [0, MAX_RANGE_M], color="#2255aa", lw=1, alpha=0.4)

    for r in np.arange(0.2, MAX_RANGE_M + 0.1, 0.2):
        ax.text(np.radians(FOV_DEG / 2 - 8), r, f"{r:.1f}m",
                color="#334455", fontsize=7, ha="center")

    # Single dot — only shown when hand detected
    scatter = ax.scatter([], [], s=400, c=["#ff2222"], zorder=5,
                         edgecolors="#ffffff", linewidths=2.0, alpha=0.95)

    # Hand label on the dot
    dot_label = ax.text(0, 0, "", color="#ffffff", fontsize=9,
                        ha="center", va="bottom", fontweight="bold", zorder=6)

    # Score bar at bottom
    ax_bar = fig.add_axes([0.15, 0.04, 0.70, 0.025])
    ax_bar.set_xlim(0, 1)
    ax_bar.set_ylim(0, 1)
    ax_bar.set_xticks([0, MATCH_THRESHOLD, 1])
    ax_bar.set_xticklabels(["0", f"threshold\n{MATCH_THRESHOLD}", "1.0"],
                            color="#445566", fontsize=7)
    ax_bar.set_yticks([])
    ax_bar.set_facecolor("#0a0a1a")
    for spine in ax_bar.spines.values():
        spine.set_edgecolor("#223344")

    bar_bg   = ax_bar.barh(0.5, 1.0, height=0.8, color="#1a1a3a", left=0)
    bar_fill = ax_bar.barh(0.5, 0.0, height=0.8, color="#ff2222", left=0)
    thresh_line = ax_bar.axvline(MATCH_THRESHOLD, color="#ffff00",
                                 linewidth=1.5, linestyle="--")

    # Status text
    title_txt  = fig.text(0.5, 0.96, "Hand Detector",
                          color="#00ffcc", fontsize=13, fontweight="bold",
                          ha="center", va="top")
    status_txt = fig.text(0.5, 0.91, "Scanning...",
                          color="#aaaaaa", fontsize=11,
                          ha="center", va="top")
    score_txt  = fig.text(0.5, 0.87, "",
                          color="#556677", fontsize=9,
                          ha="center", va="top", family="monospace")
    drop_txt   = fig.text(0.01, 0.84, "", color="#ff6644",
                          fontsize=8, family="monospace", va="top")

    frame_count = [0]
    drop_count  = [0]

    def update(_):
        drain_buffer(device, 2)
        try:
            frame_data = device.get_next_frame()[0]

            # Match against hand signature
            score = compute_match_score(frame_data, hand_sig, empty_sig)
            score_history.append(score)
            if len(score_history) > SMOOTH_FRAMES:
                score_history.pop(0)
            smooth_score = float(np.mean(score_history))

            # Update score bar
            bar_fill[0].set_width(smooth_score)
            bar_fill[0].set_color("#ff2222" if smooth_score >= MATCH_THRESHOLD else "#1a4a6a")

            detected = smooth_score >= MATCH_THRESHOLD

            if detected:
                # Find where the hand is
                range_m, angle_deg = estimate_peak_range(
                    frame_data, empty_sig, MAX_RANGE_M)

                theta = np.radians(angle_deg)
                scatter.set_offsets([[theta, range_m]])
                dot_label.set_position((theta, range_m + 0.08))
                dot_label.set_text("🎯 Hand")

                status_txt.set_text("✅  HAND DETECTED")
                status_txt.set_color("#ff2222")
            else:
                scatter.set_offsets(np.empty((0, 2)))
                dot_label.set_text("")
                status_txt.set_text("⬜  Nothing detected")
                status_txt.set_color("#445566")

            frame_count[0] += 1
            score_txt.set_text(
                f"Match score: {smooth_score:.3f}  |  "
                f"Threshold: {MATCH_THRESHOLD}  |  "
                f"Frame: {frame_count[0]}"
            )
            drop_txt.set_text("")

        except Exception as e:
            if "FRAME_ACQUISITION_FAILED" in str(e):
                drop_count[0] += 1
                drop_txt.set_text(f"⚠ Drops: {drop_count[0]}")
                drain_buffer(device, 5)
            else:
                print(f"Error: {e}")

        return scatter, status_txt, score_txt, drop_txt

    ani = animation.FuncAnimation(
        fig, update, interval=UPDATE_MS, blit=False, cache_frame_data=False
    )
    plt.show()


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    # Check signature files exist
    for f in [HAND_SIG_FILE, EMPTY_SIG_FILE]:
        if not os.path.exists(f):
            print(f"ERROR: Missing file: {f}")
            print("Run record_signature.py first to record both signatures.")
            return

    print("Loading signatures...")
    hand_sig   = np.load(HAND_SIG_FILE)
    empty_sig = np.load(EMPTY_SIG_FILE)
    print(f"  Hand signature   : {hand_sig.shape}")
    print(f"  Empty signature : {empty_sig.shape}\n")

    print("Connecting to radar...")
    with DeviceFmcw() as device:
        print("Connected!\n")
        run(device, hand_sig, empty_sig)
    print("Done.")


if __name__ == "__main__":
    main()