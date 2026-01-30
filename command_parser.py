#!/usr/bin/env python3
"""
Voice command parser for Talk Spotter.

Parses spoken commands following the protocol:
- Wake phrase: "talk spotter" (1-3 times)
- "call" + NATO phonetic callsign
- Optional: "parks" (POTA) or "summits" (SOTA) with identifier
- "frequency" + spoken frequency in MHz
- "end" to complete
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# NATO phonetic alphabet to letters
NATO_TO_LETTER = {
    'alpha': 'A', 'alfa': 'A',
    'bravo': 'B',
    'charlie': 'C',
    'delta': 'D',
    'echo': 'E',
    'foxtrot': 'F',
    'golf': 'G',
    'hotel': 'H',
    'india': 'I',
    'juliet': 'J', 'juliett': 'J',
    'kilo': 'K',
    'lima': 'L',
    'mike': 'M',
    'november': 'N',
    'oscar': 'O',
    'papa': 'P',
    'quebec': 'Q',
    'romeo': 'R',
    'sierra': 'S',
    'tango': 'T',
    'uniform': 'U',
    'victor': 'V',
    'whiskey': 'W',
    'x-ray': 'X', 'xray': 'X',
    'yankee': 'Y',
    'zulu': 'Z',
    # Numbers
    'zero': '0',
    'one': '1',
    'two': '2', 'to': '2', 'too': '2',
    'three': '3',
    'four': '4', 'for': '4',
    'five': '5',
    'six': '6',
    'seven': '7',
    'eight': '8',
    'nine': '9', 'niner': '9',
}

# Spoken numbers to digits (for frequency parsing)
SPOKEN_NUMBERS = {
    'zero': '0', 'oh': '0', 'o': '0',
    'one': '1',
    'two': '2', 'to': '2', 'too': '2',
    'three': '3',
    'four': '4', 'for': '4',
    'five': '5',
    'six': '6',
    'seven': '7',
    'eight': '8',
    'nine': '9', 'niner': '9',
    'ten': '10',
    'eleven': '11',
    'twelve': '12',
    'thirteen': '13',
    'fourteen': '14',
    'fifteen': '15',
    'sixteen': '16',
    'seventeen': '17',
    'eighteen': '18',
    'nineteen': '19',
    'twenty': '20',
    'thirty': '30',
    'forty': '40',
    'fifty': '50',
    'sixty': '60',
    'seventy': '70',
    'eighty': '80',
    'ninety': '90',
    'hundred': '00',
}


class CommandState(Enum):
    """State machine states for command parsing."""
    IDLE = "idle"                    # Waiting for wake phrase
    LISTENING = "listening"          # Heard wake phrase, waiting for command
    PARSING_CALL = "parsing_call"    # Parsing callsign
    PARSING_NET = "parsing_net"      # Parsing network (POTA/SOTA)
    PARSING_FREQ = "parsing_freq"    # Parsing frequency
    COMPLETE = "complete"            # Command complete


@dataclass
class SpotCommand:
    """Parsed spot command."""
    callsign: str = ""
    frequency_khz: float = 0.0
    network: Optional[str] = None    # "pota" or "sota"
    network_id: Optional[str] = None  # e.g., "K-1234" or "W4C/CM-001"
    comment: str = ""
    raw_text: list = field(default_factory=list)

    def is_valid(self) -> bool:
        """Check if we have minimum required fields."""
        return bool(self.callsign and self.frequency_khz > 0)

    def __str__(self):
        s = f"{self.callsign} on {self.frequency_khz:.1f} kHz"
        if self.network:
            s += f" ({self.network.upper()}"
            if self.network_id:
                s += f" {self.network_id}"
            s += ")"
        return s


class CommandParser:
    """
    State machine for parsing voice commands.

    Usage:
        parser = CommandParser()
        for text in transcribed_text_stream:
            command = parser.process(text)
            if command and command.is_valid():
                # Post the spot
    """

    # Common misheard variations of "talk spotter"
    WAKE_PHRASE_ALIASES = [
        "talk spotter",
        "talk sport",
        "talk spot",
        "top spot",
        "hot spot",
        "hawks potter",
        "talk potter",
        "talks potter",
        "talks spotter",
        "talk spotted",
    ]

    def __init__(self, wake_phrase: str = "talk spotter",
                 command_timeout: float = 30.0):
        self.wake_phrase = wake_phrase.lower()
        self.wake_phrases = [wp.lower() for wp in self.WAKE_PHRASE_ALIASES]
        if self.wake_phrase not in self.wake_phrases:
            self.wake_phrases.append(self.wake_phrase)
        self.command_timeout = command_timeout  # Seconds before auto-finalizing
        self.state = CommandState.IDLE
        self.current_command = SpotCommand()
        self._callsign_parts = []
        self._freq_parts = []
        self._timeout_words = 0  # Count words since last meaningful input
        self.max_idle_words = 20  # Reset if too many words without progress
        self._command_start_time: Optional[float] = None  # When we heard wake phrase

    def reset(self):
        """Reset parser to idle state."""
        self.state = CommandState.IDLE
        self.current_command = SpotCommand()
        self._callsign_parts = []
        self._freq_parts = []
        self._timeout_words = 0
        self._command_start_time = None

    def process(self, text: str) -> Optional[SpotCommand]:
        """
        Process transcribed text and return completed command if ready.

        Args:
            text: Transcribed text to process

        Returns:
            SpotCommand if command is complete, None otherwise
        """
        if not text:
            return None

        text_lower = text.lower().strip()
        words = text_lower.split()

        self.current_command.raw_text.append(text)

        # Check for wake phrase in any state (can restart)
        heard_wake = any(wp in text_lower for wp in self.wake_phrases)
        if heard_wake:
            self.state = CommandState.LISTENING
            self._timeout_words = 0
            self._command_start_time = time.time()
            print(f"[WAKE] Heard wake phrase, listening for command...")
            return None

        # Check for time-based timeout (auto-finalize if we have enough data)
        if self._command_start_time and self.state != CommandState.IDLE:
            elapsed = time.time() - self._command_start_time
            if elapsed > self.command_timeout:
                print(f"[TIMEOUT] {elapsed:.1f}s elapsed, attempting to finalize...")
                return self._try_auto_finalize()

        # State machine
        if self.state == CommandState.IDLE:
            # Just waiting for wake phrase
            return None

        elif self.state == CommandState.LISTENING:
            # Looking for "call" as a standalone word to start callsign
            if 'call' in words:
                self.state = CommandState.PARSING_CALL
                # Get words after "call"
                idx = words.index('call')
                self._process_callsign_words(words[idx+1:])
                print(f"[PARSE] Starting callsign: {self._callsign_parts}")
            elif 'end' in words:
                return self._finalize()
            else:
                self._timeout_words += len(words)

        elif self.state == CommandState.PARSING_CALL:
            # Check for transition words
            if 'frequency' in words:
                self._finalize_callsign()
                self.state = CommandState.PARSING_FREQ
                idx = words.index('frequency')
                self._process_freq_words(words[idx+1:])
            elif 'parks' in words or 'pota' in words:
                self._finalize_callsign()
                self.current_command.network = 'pota'
                self.state = CommandState.PARSING_NET
            elif 'summits' in words or 'sota' in words:
                self._finalize_callsign()
                self.current_command.network = 'sota'
                self.state = CommandState.PARSING_NET
            elif 'end' in words:
                self._finalize_callsign()
                return self._finalize()
            else:
                self._process_callsign_words(words)

        elif self.state == CommandState.PARSING_NET:
            # Looking for network ID or frequency
            if 'frequency' in words:
                self.state = CommandState.PARSING_FREQ
                idx = words.index('frequency')
                self._process_freq_words(words[idx+1:])
            elif 'end' in words:
                return self._finalize()
            else:
                # Try to extract network ID (e.g., "K 1234" or "kilo one two three four")
                self._process_network_id(words)
                self._timeout_words += len(words)

        elif self.state == CommandState.PARSING_FREQ:
            if 'end' in words:
                self._finalize_frequency()
                return self._finalize()
            else:
                self._process_freq_words(words)

        # Check for word-based timeout (too many unrecognized words)
        if self._timeout_words > self.max_idle_words:
            print(f"[TIMEOUT] Too many words without progress, attempting to finalize...")
            return self._try_auto_finalize()

        return None

    def _try_auto_finalize(self) -> Optional[SpotCommand]:
        """Try to finalize the command; reset if invalid."""
        self._finalize_callsign()
        self._finalize_frequency()

        if self.current_command.is_valid():
            command = self.current_command
            print(f"[AUTO-COMPLETE] {command}")
            self.reset()
            return command
        else:
            print(f"[INCOMPLETE] Cannot auto-complete - call={self.current_command.callsign}, freq={self.current_command.frequency_khz}")
            self.reset()
            return None

    def check_timeout(self) -> Optional[SpotCommand]:
        """
        Check for time-based timeout without new input.

        Call this periodically from the main loop to handle the case
        where the user goes silent after giving a partial command.
        """
        if self._command_start_time and self.state != CommandState.IDLE:
            elapsed = time.time() - self._command_start_time
            if elapsed > self.command_timeout:
                print(f"[TIMEOUT] {elapsed:.1f}s elapsed (no new input), attempting to finalize...")
                return self._try_auto_finalize()
        return None

    def _process_callsign_words(self, words: list):
        """Extract callsign characters from NATO phonetic words."""
        for word in words:
            word = word.lower().strip('.,!?')
            if word in NATO_TO_LETTER:
                self._callsign_parts.append(NATO_TO_LETTER[word])
                self._timeout_words = 0
            elif word.isalnum() and len(word) == 1:
                # Single letter/digit spoken directly
                self._callsign_parts.append(word.upper())
                self._timeout_words = 0

    def _finalize_callsign(self):
        """Convert collected parts to callsign."""
        if self._callsign_parts:
            self.current_command.callsign = ''.join(self._callsign_parts)
            print(f"[PARSE] Callsign: {self.current_command.callsign}")
            self._callsign_parts = []

    def _process_freq_words(self, words: list):
        """Extract frequency from spoken words."""
        for word in words:
            word = word.lower().strip('.,!?')
            if word in SPOKEN_NUMBERS:
                self._freq_parts.append(SPOKEN_NUMBERS[word])
                self._timeout_words = 0
            elif word in ('decimal', 'point', 'dot'):
                self._freq_parts.append('.')
                self._timeout_words = 0
            elif word.isdigit():
                self._freq_parts.append(word)
                self._timeout_words = 0

    def _finalize_frequency(self):
        """Convert collected parts to frequency in kHz."""
        if not self._freq_parts:
            return

        # Join parts and parse
        freq_str = ''.join(self._freq_parts)

        # Handle spoken frequencies:
        # - "one four two five zero" -> "14250" -> 14250 kHz (direct)
        # - "one four point two five" -> "14.25" -> 14250 kHz (MHz spoken, convert to kHz)
        # - "one four six five two zero" -> "146520" -> 146520 kHz (VHF, direct)
        try:
            freq = float(freq_str)
            # If it has a decimal or is < 1000, user probably spoke in MHz
            if '.' in freq_str or freq < 1000:
                self.current_command.frequency_khz = freq * 1000
            else:
                # Already in kHz
                self.current_command.frequency_khz = freq
            print(f"[PARSE] Frequency: {self.current_command.frequency_khz:.1f} kHz")
        except ValueError:
            print(f"[WARN] Could not parse frequency from: {freq_str}")

        self._freq_parts = []

    def _process_network_id(self, words: list):
        """Try to extract POTA/SOTA park/summit ID."""
        # This is tricky - IDs like "K-1234" might come as "kilo dash one two three four"
        # or "K 1234" or various other forms
        # For now, collect alphanumeric parts
        parts = []
        for word in words:
            word = word.lower().strip('.,!?')
            if word in NATO_TO_LETTER:
                parts.append(NATO_TO_LETTER[word])
            elif word in SPOKEN_NUMBERS:
                parts.append(SPOKEN_NUMBERS[word])
            elif word in ('dash', 'hyphen'):
                parts.append('-')
            elif word in ('slash', 'stroke'):
                parts.append('/')

        if parts:
            self.current_command.network_id = ''.join(parts)

    def _finalize(self) -> Optional[SpotCommand]:
        """Finalize and return the command."""
        self._finalize_callsign()
        self._finalize_frequency()

        if self.current_command.is_valid():
            command = self.current_command
            print(f"[COMPLETE] {command}")
            self.reset()
            return command
        else:
            print(f"[INCOMPLETE] Missing required fields - call={self.current_command.callsign}, freq={self.current_command.frequency_khz}")
            self.reset()
            return None


def parse_frequency_text(text: str) -> Optional[float]:
    """
    Parse a spoken frequency into kHz.

    Users naturally speak frequencies in MHz with decimals, so we convert:
    - "one four two five zero" -> 14250 kHz (direct, no decimal)
    - "one four point two five" -> 14250 kHz (14.25 MHz spoken)
    - "seven point two zero five" -> 7205 kHz (7.205 MHz spoken)
    - "one four six five two zero" -> 146520 kHz (VHF, direct)
    """
    words = text.lower().split()
    parts = []

    for word in words:
        word = word.strip('.,!?')
        if word in SPOKEN_NUMBERS:
            parts.append(SPOKEN_NUMBERS[word])
        elif word in ('decimal', 'point', 'dot'):
            parts.append('.')
        elif word.isdigit():
            parts.append(word)

    if not parts:
        return None

    try:
        freq_str = ''.join(parts)
        freq = float(freq_str)
        # If decimal present or small number, user spoke in MHz
        if '.' in freq_str or freq < 1000:
            return freq * 1000
        return freq
    except ValueError:
        return None


def parse_nato_callsign(text: str) -> str:
    """
    Parse NATO phonetic callsign to letters/numbers.

    Example:
        "alpha charlie one uniform charlie" -> "AC1UC"
    """
    words = text.lower().split()
    result = []

    for word in words:
        word = word.strip('.,!?')
        if word in NATO_TO_LETTER:
            result.append(NATO_TO_LETTER[word])
        elif word.isalnum() and len(word) == 1:
            result.append(word.upper())

    return ''.join(result)
