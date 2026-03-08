"""
radar/simulation.py
-------------------
Synthetic Range-Doppler source for development and testing.
Drop-in replacement for InfineonRadar — no hardware needed.
"""

import numpy as np
from .base import RadarSource


class SimulatedRadar(RadarSource):
    """Generates realistic-looking Range-Doppler maps with fake targets."""

    def __init__(self, num_range: int = 64, num_doppler: int = 32):
        self.num_range = num_range
        self.num_doppler = num_doppler

    # open() / close() are no-ops for simulation (inherited defaults are fine)

    def get_frame(self) -> np.ndarray:
        frame = np.random.rand(self.num_doppler, self.num_range) * 0.05

        n_targets = np.random.randint(1, 4)
        for _ in range(n_targets):
            r = np.random.randint(5, self.num_range - 5)
            d = np.random.randint(1, self.num_doppler - 1)
            strength = np.random.uniform(0.5, 1.0)
            for dr in range(-2, 3):
                for rr in range(-2, 3):
                    ri, di = r + rr, d + dr
                    if 0 <= ri < self.num_range and 0 <= di < self.num_doppler:
                        frame[di, ri] += strength * np.exp(-(dr**2 + rr**2) / 2)

        return frame
