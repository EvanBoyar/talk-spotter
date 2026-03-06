#!/usr/bin/env python3
"""
Vosk grammar vocabulary for Talk Spotter command recognition.

When grammar is passed to KaldiRecognizer, Vosk constrains its decoder to only
output tokens from the provided list. This improves accuracy for the structured
command protocol (NATO phonetics, number words, command keywords) and eliminates
hallucinations from background radio noise.

Use in spot mode or when testing command recognition with --grammar flag.
"""

import json

from command_parser import NATO_TO_LETTER, SPOKEN_NUMBERS


# Multi-word wake phrase entries - treated as a unit by the decoder,
# which biases recognition toward the full sequence.
_WAKE_PHRASES = [
    "talk spotter",
    "talks spotter",
]

# Single-word command keywords used by the state machine.
_COMMAND_WORDS = [
    "call",
    "frequency",
    "parks",
    "summits",
    "pota",
    "sota",
    "end",
    "complete",
]

# Separators used in frequency and network ID parsing.
_SEPARATORS = [
    "decimal",
    "point",
    "dot",
    "dash",
    "hyphen",
    "slash",
    "stroke",
]

# Derive NATO phonetics and number words directly from command_parser constants
# so the grammar stays in sync automatically.
_NATO_WORDS = list(NATO_TO_LETTER.keys())
# "x-ray" contains a hyphen which isn't valid in Vosk grammar tokens;
# "xray" is already present as an alternate in NATO_TO_LETTER.
_NATO_WORDS = [w for w in _NATO_WORDS if w != "x-ray"]

# "o" is too short and ambiguous as a standalone token; exclude it.
_NUMBER_WORDS = [w for w in SPOKEN_NUMBERS.keys() if w != "o"]

# "[unk]" maps out-of-vocabulary audio to an ignorable token rather than
# forcing a bad match from the vocabulary.
_UNK = ["[unk]"]

COMMAND_GRAMMAR_WORDS: list[str] = (
    _WAKE_PHRASES
    + _COMMAND_WORDS
    + _SEPARATORS
    + _NATO_WORDS
    + _NUMBER_WORDS
    + _UNK
)


def build_grammar_json() -> str:
    """Return the grammar as a JSON string ready to pass to KaldiRecognizer."""
    return json.dumps(COMMAND_GRAMMAR_WORDS)
