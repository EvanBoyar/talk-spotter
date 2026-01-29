#!/usr/bin/env python3
"""
Shared transcription and keyword detection for Talk Spotter.
"""

import json
import os
from vosk import Model, KaldiRecognizer


class Transcriber:
    """Speech-to-text transcription using Vosk."""

    def __init__(self, model_path: str, sample_rate: int = 16000):
        self.model_path = model_path
        self.sample_rate = sample_rate
        self.model = None
        self.recognizer = None

    def start(self):
        """Initialize the Vosk model and recognizer."""
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(
                f"Vosk model not found at '{self.model_path}'. "
                f"Download from https://alphacephei.com/vosk/models"
            )

        print(f"Loading Vosk model from: {self.model_path}")
        self.model = Model(self.model_path)
        self.recognizer = KaldiRecognizer(self.model, self.sample_rate)
        print("Vosk model loaded successfully")

    def process_audio(self, audio_data: bytes) -> tuple[str, str]:
        """
        Process audio data and return (final_text, partial_text).

        Args:
            audio_data: Raw PCM audio bytes (16-bit signed, mono)

        Returns:
            Tuple of (final_text, partial_text). Only one will be non-empty.
        """
        if self.recognizer.AcceptWaveform(audio_data):
            result = json.loads(self.recognizer.Result())
            return result.get("text", ""), ""
        else:
            partial = json.loads(self.recognizer.PartialResult())
            return "", partial.get("partial", "")

    def get_final_result(self) -> str:
        """Get any remaining text after processing is complete."""
        result = json.loads(self.recognizer.FinalResult())
        return result.get("text", "")


def detect_keywords(text: str, keywords: list) -> list:
    """
    Check if any keywords are present in the text.

    Args:
        text: Text to search in
        keywords: List of keywords to look for

    Returns:
        List of found keywords (may be empty)
    """
    if not text or not keywords:
        return []
    text_lower = text.lower()
    return [kw for kw in keywords if kw.lower() in text_lower]
