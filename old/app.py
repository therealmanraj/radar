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
NUM_CHIRPS      = 32
NUM_SAMPLES     = 64
START_FREQ_HZ   = 60e9
END_FREQ_HZ     = 61.5e9
CHIRP_REP_TIME  = 0.5e-3   # seconds between chirps
ADC_BITS        = 12

# Derived physical constants
_C              = 3e8
_BW             = END_FREQ_HZ - START_FREQ_HZ                         # 1.5 GHz
_FC             = (START_FREQ_HZ + END_FREQ_HZ) / 2                   # 60.75 GHz
_LAMBDA         = _C / _FC                                             # ~4.93e-3 m
RANGE_RES_M     = _C / (2 * _BW)                                       # 0.1 m per bin
V_MAX_MS        = _LAMBDA / (4 * CHIRP_REP_TIME)                       # ~2.47 m/s
V_MAX_KMH       = V_MAX_MS * 3.6                                       # ~8.89 km/h
MAX_RANGE_CM    = (NUM_SAMPLES // 2) * RANGE_RES_M * 100               # 320 cm

# dBFS normalisation: two Hanning windows (gain 0.5 each) + two FFTs
ADC_FULL_SCALE  = 2 ** (ADC_BITS - 1)                                  # 2048
FULL_SCALE_FFT  = ADC_FULL_SCALE * NUM_SAMPLES * NUM_CHIRPS / 4        # 1,048,576

# Axis arrays (computed once)
_VEL_AXIS_KMH    = np.linspace(-V_MAX_KMH, V_MAX_KMH, NUM_CHIRPS)
RD_EXTENT        = [_VEL_AXIS_KMH[0], _VEL_AXIS_KMH[-1], 0, MAX_RANGE_CM]


def compute_rd_map(frame_list: list) -> np.ndarray:
    """
    Convert raw SDK frame into a Range-Doppler magnitude map.
    frame_list: output of device.get_next_frame() — list with one
                (num_rx, num_chirps, num_samples) array.
    Returns: 2D float array shaped (num_samples//2, num_chirps)
             i.e. (range_bins, velocity_bins) — rows=range (Y), cols=velocity (X)
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

    # Transpose: (num_chirps, num_samples//2) → (num_samples//2, num_chirps)
    # so that rows=range (Y axis) and cols=velocity (X axis) in imshow
    return np.abs(rd_map).T   # (32 range_bins, 32 velocity_bins)


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
def render_frame(display: np.ndarray, extent: list, is_dbfs: bool = True):
    """
    Draw one Range-Doppler heatmap frame.

    display : 2D array shaped (range_bins, velocity_bins)
    extent  : [v_min_kmh, v_max_kmh, range_min_cm, range_max_cm]
    is_dbfs : True when display values are in dBFS
    """
    global frame_count
    fig, ax = plt.subplots(figsize=(9, 4))
    im = ax.imshow(
        display,
        aspect="auto",
        origin="lower",
        extent=extent,
        cmap=color_scale,
        interpolation="bilinear",
    )
    ax.set_xlabel("Radial velocity  [km/h]   ← approaching  |  receding →")
    ax.set_ylabel("Range  [cm]")
    ax.axvline(0, color="white", linewidth=0.5, linestyle="--", alpha=0.4)
    ax.set_title(f"Range-Doppler Map | Frame {frame_count}")
    fig.colorbar(im, ax=ax, label="dBFS" if is_dbfs else "Amplitude (linear)")
    fig.tight_layout()
    heatmap_placeholder.pyplot(fig, use_container_width=True)
    plt.close(fig)

    if show_stats:
        peak_rc  = np.unravel_index(display.argmax(), display.shape)  # (row=range, col=vel)
        v_step   = (extent[1] - extent[0]) / display.shape[1]
        r_step   = (extent[3] - extent[2]) / display.shape[0]
        peak_vel = extent[0] + peak_rc[1] * v_step
        peak_rng = extent[2] + peak_rc[0] * r_step
        stats_placeholder.metric("Frame #", frame_count)
        stats_placeholder.metric("Peak", f"{display.max():.1f} {'dBFS' if is_dbfs else ''}")
        stats_placeholder.metric("Peak range", f"{peak_rng:.0f} cm")
        stats_placeholder.metric("Peak velocity", f"{peak_vel:+.1f} km/h")
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
                    raw  = device.get_next_frame()  # blocks until next frame is ready
                    rd   = compute_rd_map(raw)       # (range_bins, vel_bins), linear
                    dbfs = 20 * np.log10(np.clip(rd, 1e-6, FULL_SCALE_FFT) / FULL_SCALE_FFT)
                    render_frame(dbfs, RD_EXTENT, is_dbfs=True)

        except Exception as e:
            st.error(f"SDK error: {e}")
            st.session_state.running = False

    else:
        # Simulation: build a plausible physical extent from sidebar sliders
        sim_range_max_cm = num_range_bins * 10
        sim_extent = [-V_MAX_KMH, V_MAX_KMH, 0, sim_range_max_cm]
        while st.session_state.running:
            t0 = time.time()
            # get_simulated_frame returns (num_doppler, num_range); transpose to (range, vel)
            frame = get_simulated_frame(num_range_bins, num_doppler_bins).T
            dbfs  = 20 * np.log10(np.clip(frame, 1e-6, 1.0) / 1.0)
            render_frame(dbfs, sim_extent, is_dbfs=True)
            elapsed = time.time() - t0
            remaining = frame_delay - elapsed
            if remaining > 0:
                time.sleep(remaining)
else:
    st.info("Press **Start** to begin streaming the radar heatmap.")

    # Show a static example heatmap so the UI is not blank
    ex_frame   = get_simulated_frame(num_range_bins, num_doppler_bins).T
    ex_dbfs    = 20 * np.log10(np.clip(ex_frame, 1e-6, 1.0) / 1.0)
    ex_rng_max = num_range_bins * 10
    ex_extent  = [-V_MAX_KMH, V_MAX_KMH, 0, ex_rng_max]

    fig, ax = plt.subplots(figsize=(9, 4))
    im = ax.imshow(ex_dbfs, aspect="auto", origin="lower",
                   extent=ex_extent, cmap=color_scale, interpolation="bilinear")
    ax.set_title("Example (static) — press Start to animate")
    ax.set_xlabel("Radial velocity  [km/h]")
    ax.set_ylabel("Range  [cm]")
    ax.axvline(0, color="white", linewidth=0.5, linestyle="--", alpha=0.4)
    fig.colorbar(im, ax=ax, label="dBFS")
    fig.tight_layout()
    heatmap_placeholder.pyplot(fig, use_container_width=True)
    plt.close(fig)
