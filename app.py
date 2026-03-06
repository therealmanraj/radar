"""
app.py
------
Streamlit heatmap GUI for the BGT60TR13C radar.

Phase 1 (NOW): Fake heatmap using numpy random data.
Phase 2 (NEXT): Replace the data source with real SDK frames.

Run: streamlit run app.py
"""

import streamlit as st
import numpy as np
import time
import matplotlib.pyplot as plt

# -----------------------------------------------------------------------
# PAGE CONFIG
# -----------------------------------------------------------------------
st.set_page_config(
    page_title="BGT60TR13C Radar Heatmap",
    page_icon="📡",
    layout="wide",
)

st.title("BGT60TR13C Radar — Live Heatmap")
st.caption("Infineon DEMO board | 60 GHz FMCW | macOS")

# -----------------------------------------------------------------------
# SIDEBAR CONTROLS
# -----------------------------------------------------------------------
with st.sidebar:
    st.header("Settings")

    data_source = st.radio(
        "Data source",
        ["Simulation (fake)", "Real SDK (ifxradarsdk)"],
        index=0,
    )

    num_range_bins = st.slider("Range bins", 32, 256, 64, step=32)
    num_doppler_bins = st.slider("Doppler bins", 8, 64, 32, step=8)
    fps = st.slider("Target FPS", 1, 20, 5)
    color_scale = st.selectbox("Color scale", ["viridis", "plasma", "hot", "RdBu_r"])
    log_scale = st.checkbox("Log scale (dB)", value=True)
    show_stats = st.checkbox("Show frame stats", value=True)

    st.divider()
    st.markdown("""
    **LED status guide:**
    - Steady green → normal
    - Fast blink → bootloader/error
    - Off → power issue
    """)

# -----------------------------------------------------------------------
# DATA SOURCE: SIMULATION
# -----------------------------------------------------------------------
def get_simulated_frame(num_range: int, num_doppler: int) -> np.ndarray:
    """
    Generate a fake Range-Doppler map (2D power spectrum).
    Returns a 2D float array shaped (num_doppler, num_range).

    REPLACE THIS FUNCTION with real SDK code in Phase 2.
    """
    # Background noise floor
    frame = np.random.rand(num_doppler, num_range) * 0.05

    # Add 1-3 synthetic targets at random positions
    n_targets = np.random.randint(1, 4)
    for _ in range(n_targets):
        r = np.random.randint(5, num_range - 5)
        d = np.random.randint(1, num_doppler - 1)
        strength = np.random.uniform(0.5, 1.0)
        # Gaussian blob to simulate radar peak spread
        for dr in range(-2, 3):
            for rr in range(-2, 3):
                ri, di = r + rr, d + dr
                if 0 <= ri < num_range and 0 <= di < num_doppler:
                    frame[di, ri] += strength * np.exp(-(dr**2 + rr**2) / 2)

    return frame


# -----------------------------------------------------------------------
# DATA SOURCE: REAL SDK
# -----------------------------------------------------------------------
NUM_CHIRPS  = 32
NUM_SAMPLES = 64

def compute_rd_map(frame_list: list) -> np.ndarray:
    """
    Convert raw SDK frame into a Range-Doppler magnitude map.
    frame_list: output of device.get_next_frame() — list with one
                (num_rx, num_chirps, num_samples) array.
    Returns: 2D float array (num_chirps, num_samples//2)
    """
    rx_data = frame_list[0]          # (3, 32, 64)
    rx0 = rx_data[0].astype(float)   # (32, 64) — use RX0

    # Hanning windows to reduce sidelobes
    win_range   = np.hanning(rx0.shape[1])
    win_doppler = np.hanning(rx0.shape[0])
    windowed = rx0 * win_range[np.newaxis, :] * win_doppler[:, np.newaxis]

    # Range FFT → one-sided
    range_fft = np.fft.fft(windowed, axis=1)[:, :rx0.shape[1] // 2]

    # Doppler FFT across chirps, centred
    rd_map = np.fft.fftshift(np.fft.fft(range_fft, axis=0), axes=0)

    return np.abs(rd_map)   # (num_chirps, num_samples//2)


# -----------------------------------------------------------------------
# MAIN LOOP
# -----------------------------------------------------------------------
col1, col2 = st.columns([3, 1])

with col1:
    heatmap_placeholder = st.empty()

with col2:
    stats_placeholder = st.empty()

frame_count = 0
frame_delay = 1.0 / fps

# Use session state to allow stop button
if "running" not in st.session_state:
    st.session_state.running = False

start_col, stop_col = st.columns(2)
with start_col:
    if st.button("Start", type="primary"):
        st.session_state.running = True
with stop_col:
    if st.button("Stop"):
        st.session_state.running = False

# -----------------------------------------------------------------------
# RENDER HELPERS
# -----------------------------------------------------------------------
def render_frame(display: np.ndarray):
    """Draw one heatmap frame and update stats."""
    global frame_count
    fig, ax = plt.subplots(figsize=(9, 4))
    im = ax.imshow(
        display,
        aspect="auto",
        origin="lower",
        cmap=color_scale,
        interpolation="bilinear",
    )
    ax.set_xlabel("Range bin →")
    ax.set_ylabel("← Closing | Doppler bin | Opening →")
    ax.set_title(f"Range-Doppler Map | Frame {frame_count}")
    fig.colorbar(im, ax=ax, label="Power (dB)" if log_scale else "Power (linear)")
    fig.tight_layout()
    heatmap_placeholder.pyplot(fig, use_container_width=True)
    plt.close(fig)

    if show_stats:
        stats_placeholder.metric("Frame #", frame_count)
        stats_placeholder.metric("Peak power", f"{display.max():.1f} {'dB' if log_scale else ''}")
        stats_placeholder.metric(
            "Peak range bin", f"{np.unravel_index(display.argmax(), display.shape)[1]}"
        )
    frame_count += 1


# -----------------------------------------------------------------------
# RENDER LOOP
# -----------------------------------------------------------------------
if st.session_state.running:
    if data_source == "Real SDK (ifxradarsdk)":
        # Open device ONCE, then loop — never open/close per frame
        try:
            from ifxradarsdk.fmcw import DeviceFmcw
            from ifxradarsdk.fmcw.types import FmcwSimpleSequenceConfig, FmcwSequenceChirp

            with DeviceFmcw() as device:
                # Keep radar frame rate at a safe fixed value (5 fps = 200 ms).
                # The UI fps slider only affects how often we redraw, not how
                # fast the sensor acquires — acquiring too fast overflows the
                # USB buffer and causes IFX_ERROR_FRAME_ACQUISITION_FAILED.
                RADAR_FPS = 5
                config = FmcwSimpleSequenceConfig(
                    frame_repetition_time_s=1.0 / RADAR_FPS,
                    chirp_repetition_time_s=0.5e-3,
                    num_chirps=NUM_CHIRPS,
                    tdm_mimo=False,
                    chirp=FmcwSequenceChirp(
                        start_frequency_Hz=60e9,
                        end_frequency_Hz=61.5e9,
                        sample_rate_Hz=1e6,
                        num_samples=NUM_SAMPLES,
                        rx_mask=7,
                        tx_mask=1,
                        tx_power_level=31,
                        lp_cutoff_Hz=500000,
                        hp_cutoff_Hz=80000,
                        if_gain_dB=33,
                    ),
                )
                sequence = device.create_simple_sequence(config)
                device.set_acquisition_sequence(sequence)

                while st.session_state.running:
                    raw = device.get_next_frame()  # blocks until next frame is ready
                    rd = compute_rd_map(raw)
                    display = 20 * np.log10(np.clip(rd, 1e-6, None)) if log_scale else rd
                    render_frame(display)

        except Exception as e:
            st.error(f"SDK error: {e}")
            st.session_state.running = False

    else:
        while st.session_state.running:
            t0 = time.time()
            frame = get_simulated_frame(num_range_bins, num_doppler_bins)
            display = 20 * np.log10(np.clip(frame, 1e-6, None)) if log_scale else frame
            render_frame(display)
            elapsed = time.time() - t0
            remaining = frame_delay - elapsed
            if remaining > 0:
                time.sleep(remaining)
else:
    st.info("Press **Start** to begin streaming the radar heatmap.")

    # Show a static example heatmap so the UI is not blank
    ex_frame = get_simulated_frame(num_range_bins, num_doppler_bins)
    if log_scale:
        ex_frame = 20 * np.log10(np.clip(ex_frame, 1e-6, None))

    fig, ax = plt.subplots(figsize=(9, 4))
    im = ax.imshow(ex_frame, aspect="auto", origin="lower", cmap=color_scale, interpolation="bilinear")
    ax.set_title("Example (static) — press Start to animate")
    ax.set_xlabel("Range bin →")
    ax.set_ylabel("Doppler bin")
    fig.colorbar(im, ax=ax)
    fig.tight_layout()
    heatmap_placeholder.pyplot(fig, use_container_width=True)
    plt.close(fig)
