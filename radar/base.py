"""
radar/base.py
-------------
Abstract base class for all radar data sources.

To add a new source (e.g. recorded file, network socket):
  1. Subclass RadarSource
  2. Implement get_frame() → np.ndarray  shape (num_doppler, num_range)
  3. Swap it in server/app.py (one line)
"""

from abc import ABC, abstractmethod
import numpy as np


class RadarSource(ABC):
    """Plug-in interface for any radar data source."""

    @abstractmethod
    def get_frame(self) -> np.ndarray:
        """
        Return one Range-Doppler map as a 2D float array.
        Shape: (num_doppler, num_range)
        Blocking call — runs in a dedicated thread.
        """
        ...

    def open(self) -> None:
        """Open device / file. Called once before the read loop starts."""

    def close(self) -> None:
        """Release resources. Called when the server shuts down."""

    # Context-manager support so `with source:` works in the thread loop
    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *_):
        self.close()
