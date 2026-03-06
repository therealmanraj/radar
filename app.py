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
# DATA SOURCE: REAL SDK (placeholder)
# -----------------------------------------------------------------------
def get_real_sdk_frame(num_range: int, num_doppler: int) -> np.ndarray:
    """
    *** PHASE 2: REPLACE THIS WITH REAL SDK CODE ***

    Example (requires ifxradarsdk installed):

        from ifxradarsdk.fmcw import DeviceFmcw
        # ... (device must be opened once, not per frame)
        raw_frame = device.get_next_frame()  # list of rx arrays
        rx0 = raw_frame[0]  # shape: (num_chirps, num_samples)

        # Range FFT
        range_fft = np.fft.fft(rx0, axis=1)[:, :num_samples//2]

        # Doppler FFT (across chirps)
        rd_map = np.fft.fftshift(np.fft.fft(range_fft, axis=0), axes=0)

        return np.abs(rd_map)

    For now, return fake data:
    """
    st.warning("Real SDK not connected — showing simulation. Install ifxradarsdk and update get_real_sdk_frame().")
    return get_simulated_frame(num_range, num_doppler)


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
# RENDER LOOP
# -----------------------------------------------------------------------
if st.session_state.running:
    # Import here to avoid slowing down initial page load
    import matplotlib.pyplot as plt
    import matplotlib.colors as mcolors

    while st.session_state.running:
        t0 = time.time()

        # --- GET DATA ---
        if data_source == "Simulation (fake)":
            frame = get_simulated_frame(num_range_bins, num_doppler_bins)
        else:
            frame = get_real_sdk_frame(num_range_bins, num_doppler_bins)

        # --- APPLY LOG SCALE ---
        if log_scale:
            # Convert to dB, clip negative values
            display = 20 * np.log10(np.clip(frame, 1e-6, None))
        else:
            display = frame

        # --- RENDER HEATMAP ---
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

        # --- STATS ---
        if show_stats:
            stats_placeholder.metric("Frame #", frame_count)
            stats_placeholder.metric("Peak power", f"{display.max():.1f} {'dB' if log_scale else ''}")
            stats_placeholder.metric(
                "Peak range bin", f"{np.unravel_index(display.argmax(), display.shape)[1]}"
            )

        frame_count += 1

        # Pace the loop
        elapsed = time.time() - t0
        remaining = frame_delay - elapsed
        if remaining > 0:
            time.sleep(remaining)
else:
    st.info("Press **Start** to begin streaming the radar heatmap.")

    # Show a static example heatmap so the UI is not blank
    import matplotlib.pyplot as plt
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
