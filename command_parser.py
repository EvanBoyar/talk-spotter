#!/usr/bin/env python3
"""
Voice command parser for Talk Spotter.

Parses spoken commands following the protocol:
- Wake phrase: "talk spotter" (1-3 times)
- "call" + NATO phonetic callsign
- Optional: "parks" (POTA) or "summits" (SOTA) with identifier
- "frequency" + spoken frequency in MHz
- "end" to complete

Fields may appear in any order after the wake phrase.
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
#   'ten': '10', #fourteen is often misheard as "four ten", and luckily in the US at least 10.x is all digital
#   'eleven': '11',
#   'twelve': '12',
#   'thirteen': '13',
    'fourteen': '14',
#   'fifteen': '15',
#   'sixteen': '16',
#   'seventeen': '17',
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
    """Parser states."""
    IDLE = "idle"            # Waiting for wake phrase
    LISTENING = "listening"  # Accumulating words for a command


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
    Collect-then-parse voice command processor.

    Once the wake phrase is heard, all subsequent words are buffered until
    "end" or "complete" is spoken (or a timeout fires). The full buffer is
    then scanned for field keywords and each field is extracted from the
    slice between its keyword and the next one — regardless of order.

    Usage:
        parser = CommandParser()
        for text in transcribed_text_stream:
            command = parser.process(text)
            if command and command.is_valid():
                # Post the spot
    """

    # Keywords that delimit field sections in the buffer
    _FIELD_KEYWORDS = frozenset({'call', 'frequency', 'parks', 'pota', 'summits', 'sota'})
    _END_KEYWORDS = frozenset({'end', 'complete'})
    _CANCEL_KEYWORDS = frozenset({'cancel'})
    _ALL_KEYWORDS = _FIELD_KEYWORDS | _END_KEYWORDS

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
                 idle_timeout: float = 10.0,
                 session_timeout: float = 60.0):
        self.wake_phrase = wake_phrase.lower()
        self.wake_phrases = [wp.lower() for wp in self.WAKE_PHRASE_ALIASES]
        if self.wake_phrase not in self.wake_phrases:
            self.wake_phrases.append(self.wake_phrase)
        self.idle_timeout = idle_timeout      # Seconds of silence before auto-finalizing
        self.session_timeout = session_timeout  # Hard cap from wake phrase
        self.state = CommandState.IDLE
        self.current_command = SpotCommand()
        self._buffer: list = []          # Words accumulated since wake phrase
        self._callsign_parts: list = []
        self._freq_parts: list = []
        self._command_start_time: Optional[float] = None
        self._last_input_time: Optional[float] = None

    def reset(self):
        """Reset parser to idle state."""
        self.state = CommandState.IDLE
        self.current_command = SpotCommand()
        self._buffer = []
        self._callsign_parts = []
        self._freq_parts = []
        self._command_start_time = None
        self._last_input_time = None

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
        self.current_command.raw_text.append(text)

        # Check for wake phrase in any state (can restart)
        for wp in self.wake_phrases:
            idx = text_lower.find(wp)
            if idx != -1:
                self.reset()
                self.state = CommandState.LISTENING
                self._command_start_time = time.time()
                print(f"[WAKE] Heard wake phrase, listening for command...")
                remaining = text_lower[idx + len(wp):].strip()
                if remaining:
                    return self.process(remaining)
                return None

        if self.state == CommandState.IDLE:
            return None

        # LISTENING: clean and normalize words before buffering
        words = self._merge_xray([w.strip('.,!?') for w in text_lower.split()])
        words = self._normalize_keywords(words)

        # Cancel: discard everything and return to idle
        if any(w in self._CANCEL_KEYWORDS for w in words):
            print("[CANCEL] Command cancelled, returning to idle.")
            self.reset()
            return None

        # Check if this utterance contains the end keyword
        end_idx = next((i for i, w in enumerate(words) if w in self._END_KEYWORDS), None)
        if end_idx is not None:
            self._buffer.extend(words[:end_idx])
            return self._parse_and_finalize()

        self._buffer.extend(words)
        self._last_input_time = time.time()

        # Session timeout: hard cap from wake phrase
        if self._command_start_time and self._last_input_time - self._command_start_time > self.session_timeout:
            print(f"[TIMEOUT] {self._last_input_time - self._command_start_time:.1f}s session cap, attempting to finalize...")
            return self._parse_and_finalize()

        # Safety valve: reset if buffer grows unreasonably large
        if len(self._buffer) > 60:
            print(f"[TIMEOUT] Buffer too large, attempting to finalize...")
            return self._parse_and_finalize()

        return None

    def check_timeout(self) -> Optional[SpotCommand]:
        """
        Check for timeout without new input.

        Call this periodically from the main loop to handle the case
        where the user goes silent after giving a partial command.

        Two conditions trigger finalization:
        - Idle timeout: no words received for idle_timeout seconds
        - Session timeout: hard cap of session_timeout seconds from wake phrase
        """
        if self.state == CommandState.IDLE:
            return None
        now = time.time()
        if self._last_input_time and now - self._last_input_time > self.idle_timeout:
            print(f"[TIMEOUT] {now - self._last_input_time:.1f}s idle, attempting to finalize...")
            return self._parse_and_finalize()
        if self._command_start_time and now - self._command_start_time > self.session_timeout:
            print(f"[TIMEOUT] {now - self._command_start_time:.1f}s session cap, attempting to finalize...")
            return self._parse_and_finalize()
        return None

    def _parse_buffer(self):
        """
        Scan the accumulated word buffer for field keywords and extract
        each field from the slice between its keyword and the next one.
        Field order does not matter. If a keyword appears multiple times,
        only the last occurrence is used — it overrides all earlier ones.
        """
        buf = self._buffer
        # Keep only the last occurrence of each keyword so repeated keywords
        # (e.g. "call ... call ...") use the most recent section.
        last_seen: dict = {}
        for i, w in enumerate(buf):
            if w in self._ALL_KEYWORDS:
                last_seen[w] = i
        kw_positions = sorted((i, w) for w, i in last_seen.items())

        for j, (i, kw) in enumerate(kw_positions):
            if kw in self._END_KEYWORDS:
                continue
            # Section: words after this keyword up to the start of the next keyword
            next_i = kw_positions[j + 1][0] if j + 1 < len(kw_positions) else len(buf)
            section = buf[i + 1:next_i]

            if kw == 'call':
                self._process_callsign_words(section)
            elif kw == 'frequency':
                self._process_freq_words(section)
            elif kw in ('parks', 'pota'):
                self.current_command.network = 'pota'
                self._process_network_id(section)
            elif kw in ('summits', 'sota'):
                self.current_command.network = 'sota'
                self._process_network_id(section)

    def _parse_and_finalize(self) -> Optional[SpotCommand]:
        """Parse the buffer and return the command if valid, else reset."""
        self._parse_buffer()
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

    # Tens and units values for compound number merging (e.g. "twenty eight" → "28")
    _COMPOUND_TENS = {
        'twenty': 20, 'thirty': 30, 'forty': 40, 'fifty': 50,
        'sixty': 60, 'seventy': 70, 'eighty': 80, 'ninety': 90,
    }
    _COMPOUND_UNITS = {
        'one': 1, 'two': 2, 'to': 2, 'too': 2,
        'three': 3, 'four': 4, 'for': 4,
        'five': 5, 'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'niner': 9,
    }

    @staticmethod
    def _merge_compound_numbers(words: list) -> list:
        """
        Merge TENS+UNITS bigrams into a single compound number string.

        Examples:
            ["twenty", "eight"] -> ["28"]
            ["twenty", "eight", "decimal", "five"] -> ["28", "decimal", "five"]
            ["one", "four", "two"] -> ["one", "four", "two"]  (no tens word, unchanged)
        """
        merged = []
        i = 0
        while i < len(words):
            tens_val = CommandParser._COMPOUND_TENS.get(words[i])
            if tens_val is not None and i + 1 < len(words):
                units_val = CommandParser._COMPOUND_UNITS.get(words[i + 1])
                if units_val is not None:
                    merged.append(str(tens_val + units_val))
                    i += 2
                    continue
            merged.append(words[i])
            i += 1
        return merged

    @staticmethod
    def _normalize_keywords(words: list) -> list:
        """
        Normalize keyword aliases so the rest of the pipeline sees canonical forms.

        - "callsign"          → "call"
        - ["call", "sign"]    → ["call"]
        """
        merged = []
        i = 0
        while i < len(words):
            if words[i] == 'callsign':
                merged.append('call')
                i += 1
            elif words[i] == 'call' and i + 1 < len(words) and words[i + 1] == 'sign':
                merged.append('call')
                i += 2
            else:
                merged.append(words[i])
                i += 1
        return merged

    @staticmethod
    def _merge_xray(words: list) -> list:
        """Merge ["x", "ray"] bigrams into ["xray"] (Vosk splits x-ray into two tokens)."""
        merged = []
        i = 0
        while i < len(words):
            if words[i] == 'x' and i + 1 < len(words) and words[i + 1] == 'ray':
                merged.append('xray')
                i += 2
            else:
                merged.append(words[i])
                i += 1
        return merged

    def _process_callsign_words(self, words: list):
        """Extract callsign characters from NATO phonetic words."""
        words = self._merge_xray(words)
        for word in words:
            word = word.lower().strip('.,!?')
            if word in NATO_TO_LETTER:
                self._callsign_parts.append(NATO_TO_LETTER[word])
            elif word.isalnum() and len(word) == 1:
                # Single letter/digit spoken directly
                self._callsign_parts.append(word.upper())

    def _finalize_callsign(self):
        """Convert collected parts to callsign."""
        if self._callsign_parts:
            self.current_command.callsign = ''.join(self._callsign_parts)
            print(f"[PARSE] Callsign: {self.current_command.callsign}")
            self._callsign_parts = []

    def _process_freq_words(self, words: list):
        """Extract frequency from spoken words."""
        words = self._merge_compound_numbers(words)
        for word in words:
            word = word.lower().strip('.,!?')
            if word in SPOKEN_NUMBERS:
                self._freq_parts.append(SPOKEN_NUMBERS[word])
            elif word in ('decimal', 'point', 'dot'):
                self._freq_parts.append('.')
            elif word.isdigit():
                self._freq_parts.append(word)

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
        words = self._merge_xray(words)
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
