"""
Audio sources for Talk Spotter.

Source classes are imported lazily so the app can boot even if
optional dependencies (kiwiclient, pyrtlsdr, soundcard) are missing.
"""

from .base import AudioSource

__all__ = ['AudioSource']
