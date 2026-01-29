"""
Audio sources for Talk Spotter.
"""

from .base import AudioSource
from .kiwisdr import KiwiSDRSource
from .rtlsdr import RTLSDRSource

__all__ = ['AudioSource', 'KiwiSDRSource', 'RTLSDRSource']
