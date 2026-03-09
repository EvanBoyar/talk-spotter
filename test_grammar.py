#!/usr/bin/env python3
"""Unit tests for grammar.py — Vosk grammar vocabulary."""

import json
import unittest

from grammar import build_grammar_json, COMMAND_GRAMMAR_WORDS
from command_parser import NATO_TO_LETTER, SPOKEN_NUMBERS


class TestBuildGrammarJson(unittest.TestCase):
    """Test that build_grammar_json() returns valid JSON."""

    def test_returns_valid_json(self):
        result = build_grammar_json()
        parsed = json.loads(result)
        self.assertIsInstance(parsed, list)
        self.assertGreater(len(parsed), 0)

    def test_matches_word_list(self):
        parsed = json.loads(build_grammar_json())
        self.assertEqual(parsed, COMMAND_GRAMMAR_WORDS)


class TestNatoPhonetics(unittest.TestCase):
    """Test that NATO phonetics are included in the vocabulary."""

    def test_all_nato_present(self):
        """All NATO_TO_LETTER keys should be present, except 'x-ray' which is split."""
        for word in NATO_TO_LETTER:
            if word == "x-ray":
                # x-ray is represented as the multi-word "x ray"
                self.assertIn("x ray", COMMAND_GRAMMAR_WORDS)
            else:
                self.assertIn(word, COMMAND_GRAMMAR_WORDS,
                              f"NATO word '{word}' missing from grammar")


class TestSpokenNumbers(unittest.TestCase):
    """Test that spoken numbers are included in the vocabulary."""

    def test_all_spoken_numbers_present(self):
        """All SPOKEN_NUMBERS keys should be present, except 'o' (too ambiguous)."""
        for word in SPOKEN_NUMBERS:
            if word == "o":
                self.assertNotIn("o", COMMAND_GRAMMAR_WORDS)
            else:
                self.assertIn(word, COMMAND_GRAMMAR_WORDS,
                              f"Spoken number '{word}' missing from grammar")


class TestUnk(unittest.TestCase):
    """Test that [unk] is included."""

    def test_unk_present(self):
        self.assertIn("[unk]", COMMAND_GRAMMAR_WORDS)


class TestNoDuplicates(unittest.TestCase):
    """Test that there are no duplicate entries in the vocabulary."""

    def test_no_duplicates(self):
        seen = set()
        duplicates = []
        for word in COMMAND_GRAMMAR_WORDS:
            if word in seen:
                duplicates.append(word)
            seen.add(word)
        self.assertEqual(duplicates, [],
                         f"Duplicate words in grammar: {duplicates}")


class TestCommandKeywords(unittest.TestCase):
    """Test that command keywords are present."""

    def test_required_keywords(self):
        required = ["call", "frequency", "end", "cancel", "complete",
                     "parks", "summits", "pota", "sota", "callsign"]
        for kw in required:
            self.assertIn(kw, COMMAND_GRAMMAR_WORDS,
                          f"Command keyword '{kw}' missing from grammar")

    def test_separators(self):
        for sep in ["decimal", "point", "dot", "dash", "slash"]:
            self.assertIn(sep, COMMAND_GRAMMAR_WORDS,
                          f"Separator '{sep}' missing from grammar")


if __name__ == "__main__":
    unittest.main()
