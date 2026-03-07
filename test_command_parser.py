#!/usr/bin/env python3
"""Unit tests for command_parser.py — heavy focus on unhappy paths."""

import time
import unittest
from unittest.mock import patch

from command_parser import (
    CommandParser,
    CommandState,
    SpotCommand,
    parse_frequency_text,
    parse_nato_callsign,
)


# ---------------------------------------------------------------------------
# Static helpers (isolated, no state)
# ---------------------------------------------------------------------------

class TestMergeXray(unittest.TestCase):
    def test_basic_merge(self):
        self.assertEqual(CommandParser._merge_xray(["x", "ray"]), ["xray"])

    def test_x_alone(self):
        self.assertEqual(CommandParser._merge_xray(["x"]), ["x"])

    def test_ray_alone(self):
        self.assertEqual(CommandParser._merge_xray(["ray"]), ["ray"])

    def test_mid_sequence(self):
        self.assertEqual(
            CommandParser._merge_xray(["november", "x", "ray", "eight"]),
            ["november", "xray", "eight"],
        )

    def test_multiple_xrays(self):
        self.assertEqual(
            CommandParser._merge_xray(["x", "ray", "alpha", "x", "ray"]),
            ["xray", "alpha", "xray"],
        )

    def test_empty(self):
        self.assertEqual(CommandParser._merge_xray([]), [])


class TestMergeCompoundNumbers(unittest.TestCase):
    def test_twenty_eight(self):
        self.assertEqual(CommandParser._merge_compound_numbers(["twenty", "eight"]), ["28"])

    def test_tens_followed_by_non_unit(self):
        self.assertEqual(
            CommandParser._merge_compound_numbers(["twenty", "decimal"]),
            ["twenty", "decimal"],
        )

    def test_ninety_nine(self):
        self.assertEqual(CommandParser._merge_compound_numbers(["ninety", "nine"]), ["99"])

    def test_no_tens_word(self):
        self.assertEqual(
            CommandParser._merge_compound_numbers(["one", "four"]),
            ["one", "four"],
        )

    def test_mixed(self):
        self.assertEqual(
            CommandParser._merge_compound_numbers(["twenty", "eight", "decimal", "five"]),
            ["28", "decimal", "five"],
        )

    def test_empty(self):
        self.assertEqual(CommandParser._merge_compound_numbers([]), [])

    def test_tens_at_end(self):
        self.assertEqual(CommandParser._merge_compound_numbers(["twenty"]), ["twenty"])


class TestNormalizeKeywords(unittest.TestCase):
    def test_callsign_single_word(self):
        self.assertEqual(CommandParser._normalize_keywords(["callsign"]), ["call"])

    def test_call_sign_two_words(self):
        self.assertEqual(CommandParser._normalize_keywords(["call", "sign"]), ["call"])

    def test_call_not_followed_by_sign(self):
        self.assertEqual(
            CommandParser._normalize_keywords(["call", "november"]),
            ["call", "november"],
        )

    def test_call_sign_with_data(self):
        self.assertEqual(
            CommandParser._normalize_keywords(["call", "sign", "november"]),
            ["call", "november"],
        )

    def test_no_keywords(self):
        self.assertEqual(
            CommandParser._normalize_keywords(["november", "romeo"]),
            ["november", "romeo"],
        )


# ---------------------------------------------------------------------------
# _parse_buffer (unhappy focus)
# ---------------------------------------------------------------------------

class TestParseBuffer(unittest.TestCase):
    def setUp(self):
        self.p = CommandParser()
        self.p.state = CommandState.LISTENING

    def test_no_keywords_in_buffer(self):
        self.p._buffer = ["november", "romeo", "eight", "echo"]
        self.p._parse_buffer()
        self.assertEqual(self.p.current_command.callsign, "")
        self.assertEqual(self.p.current_command.frequency_khz, 0.0)

    def test_empty_sections(self):
        self.p._buffer = ["call", "frequency"]
        self.p._parse_buffer()
        self.p._finalize_callsign()
        self.p._finalize_frequency()
        self.assertEqual(self.p.current_command.callsign, "")
        self.assertEqual(self.p.current_command.frequency_khz, 0.0)

    def test_duplicate_keyword_last_wins(self):
        self.p._buffer = ["call", "november", "romeo", "call", "november", "romeo", "eight", "echo"]
        self.p._parse_buffer()
        self.p._finalize_callsign()
        self.assertEqual(self.p.current_command.callsign, "NR8E")

    def test_all_keywords_no_data(self):
        self.p._buffer = ["call", "frequency", "parks", "end"]
        self.p._parse_buffer()
        self.p._finalize_callsign()
        self.p._finalize_frequency()
        self.assertEqual(self.p.current_command.callsign, "")
        self.assertEqual(self.p.current_command.frequency_khz, 0.0)

    def test_unrecognized_words_dropped(self):
        self.p._buffer = ["call", "garbage", "november", "romeo"]
        self.p._parse_buffer()
        self.p._finalize_callsign()
        # "garbage" silently dropped, NR extracted
        self.assertEqual(self.p.current_command.callsign, "NR")


# ---------------------------------------------------------------------------
# process() — unhappy paths (the bulk)
# ---------------------------------------------------------------------------

class TestProcessUnhappy(unittest.TestCase):
    def setUp(self):
        self.p = CommandParser()

    def test_no_wake_phrase(self):
        result = self.p.process("call november romeo eight echo frequency one four two one nine end")
        self.assertIsNone(result)
        self.assertEqual(self.p.state, CommandState.IDLE)

    def test_wake_then_end_only(self):
        self.p.process("talk spotter")
        result = self.p.process("end")
        # INCOMPLETE: no callsign or frequency
        self.assertIsNone(result)

    def test_callsign_no_frequency(self):
        self.p.process("talk spotter")
        self.p.process("call november romeo eight echo")
        result = self.p.process("end")
        self.assertIsNone(result)

    def test_frequency_no_callsign(self):
        self.p.process("talk spotter")
        self.p.process("frequency one four two one nine")
        result = self.p.process("end")
        self.assertIsNone(result)

    def test_cancel_after_wake(self):
        self.p.process("talk spotter")
        result = self.p.process("cancel")
        self.assertIsNone(result)
        self.assertEqual(self.p.state, CommandState.IDLE)

    def test_cancel_after_partial(self):
        self.p.process("talk spotter")
        self.p.process("call november romeo eight echo")
        result = self.p.process("cancel")
        self.assertIsNone(result)
        self.assertEqual(self.p.state, CommandState.IDLE)

    def test_cancel_with_other_words(self):
        self.p.process("talk spotter")
        self.p.process("call november romeo")
        result = self.p.process("frequency cancel")
        self.assertIsNone(result)
        self.assertEqual(self.p.state, CommandState.IDLE)

    def test_wake_mid_garbage(self):
        self.p.process("something something talk spotter")
        self.assertEqual(self.p.state, CommandState.LISTENING)

    def test_second_wake_restarts(self):
        self.p.process("talk spotter")
        self.p.process("call november romeo")
        # Second wake phrase wipes the partial command
        self.p.process("talk spotter")
        self.assertEqual(self.p._buffer, [])
        self.p.process("call november romeo eight echo frequency one four two one nine")
        result = self.p.process("end")
        self.assertIsNotNone(result)
        self.assertEqual(result.callsign, "NR8E")

    def test_misheard_wake_aliases(self):
        for alias in ["talk sport", "top spot", "hawks potter", "talks spotter"]:
            p = CommandParser()
            p.process(alias)
            self.assertEqual(p.state, CommandState.LISTENING, f"Alias '{alias}' did not trigger wake")

    def test_empty_string(self):
        result = self.p.process("")
        self.assertIsNone(result)

    def test_end_as_first_word(self):
        self.p.process("talk spotter")
        result = self.p.process("end")
        self.assertIsNone(result)

    def test_garbled_nato(self):
        self.p.process("talk spotter")
        self.p.process("call november blurb eight garble")
        self.p.process("frequency one four two one nine")
        result = self.p.process("end")
        # Should still parse what it can
        self.assertIsNotNone(result)
        self.assertEqual(result.callsign, "N8")


# ---------------------------------------------------------------------------
# process() — happy paths (regression safety)
# ---------------------------------------------------------------------------

class TestProcessHappy(unittest.TestCase):
    def setUp(self):
        self.p = CommandParser()

    def test_standard_order(self):
        self.p.process("talk spotter")
        self.p.process("call november romeo eight echo")
        self.p.process("frequency one four two one nine")
        result = self.p.process("end")
        self.assertIsNotNone(result)
        self.assertEqual(result.callsign, "NR8E")
        self.assertEqual(result.frequency_khz, 14219.0)

    def test_reverse_order(self):
        self.p.process("talk spotter")
        self.p.process("frequency one four two one nine")
        self.p.process("call november romeo eight echo")
        result = self.p.process("end")
        self.assertIsNotNone(result)
        self.assertEqual(result.callsign, "NR8E")
        self.assertEqual(result.frequency_khz, 14219.0)

    def test_with_pota(self):
        self.p.process("talk spotter")
        self.p.process("call whiskey one alpha whiskey")
        self.p.process("parks kilo dash one two three four")
        self.p.process("frequency one four point two one nine")
        result = self.p.process("end")
        self.assertIsNotNone(result)
        self.assertEqual(result.callsign, "W1AW")
        self.assertEqual(result.network, "pota")
        self.assertEqual(result.network_id, "K-1234")
        self.assertAlmostEqual(result.frequency_khz, 14219.0)

    def test_with_sota(self):
        self.p.process("talk spotter")
        self.p.process("call whiskey one alpha whiskey")
        self.p.process("summits whiskey four charlie slash charlie mike dash zero zero one")
        self.p.process("frequency one four point two one nine")
        result = self.p.process("end")
        self.assertIsNotNone(result)
        self.assertEqual(result.network, "sota")
        self.assertEqual(result.network_id, "W4C/CM-001")

    def test_chunked_input(self):
        self.p.process("talk spotter")
        self.p.process("call")
        self.p.process("november")
        self.p.process("romeo")
        self.p.process("eight")
        self.p.process("echo")
        self.p.process("frequency")
        self.p.process("one four two one nine")
        result = self.p.process("end")
        self.assertIsNotNone(result)
        self.assertEqual(result.callsign, "NR8E")
        self.assertEqual(result.frequency_khz, 14219.0)

    def test_single_utterance(self):
        result = self.p.process("talk spotter call november romeo eight echo frequency one four two one nine end")
        self.assertIsNotNone(result)
        self.assertEqual(result.callsign, "NR8E")
        self.assertEqual(result.frequency_khz, 14219.0)


# ---------------------------------------------------------------------------
# Timeout paths
# ---------------------------------------------------------------------------

class TestTimeouts(unittest.TestCase):
    def test_idle_timeout_valid_data(self):
        p = CommandParser(idle_timeout=0.1)
        p.process("talk spotter")
        p.process("call november romeo eight echo frequency one four two one nine")
        time.sleep(0.15)
        result = p.check_timeout()
        self.assertIsNotNone(result)
        self.assertEqual(result.callsign, "NR8E")

    def test_idle_timeout_invalid_data(self):
        p = CommandParser(idle_timeout=0.1)
        p.process("talk spotter")
        p.process("call november romeo")
        time.sleep(0.15)
        result = p.check_timeout()
        # No frequency → invalid → None
        self.assertIsNone(result)
        self.assertEqual(p.state, CommandState.IDLE)

    def test_session_timeout(self):
        p = CommandParser(session_timeout=0.1)
        p.process("talk spotter")
        p.process("call november romeo eight echo")
        time.sleep(0.15)
        # Session cap via check_timeout
        result = p.check_timeout()
        # No frequency → invalid
        self.assertIsNone(result)
        self.assertEqual(p.state, CommandState.IDLE)

    def test_buffer_overflow(self):
        p = CommandParser()
        p.process("talk spotter")
        # Feed 61+ words to trigger buffer overflow
        big_input = " ".join(["november"] * 61)
        result = p.process(big_input)
        # Should auto-finalize (but missing frequency → None)
        self.assertIsNone(result)
        self.assertEqual(p.state, CommandState.IDLE)

    def test_idle_check_no_input_after_wake(self):
        """Wake phrase sets _command_start_time but not _last_input_time.
        Session cap should still catch it."""
        p = CommandParser(session_timeout=0.1)
        p.process("talk spotter")
        self.assertIsNone(p._last_input_time)
        time.sleep(0.15)
        result = p.check_timeout()
        self.assertIsNone(result)
        self.assertEqual(p.state, CommandState.IDLE)

    def test_check_timeout_idle_state(self):
        p = CommandParser()
        result = p.check_timeout()
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Frequency parsing edge cases
# ---------------------------------------------------------------------------

class TestFrequencyParsing(unittest.TestCase):
    def setUp(self):
        self.p = CommandParser()

    def _parse_freq(self, freq_words):
        """Helper: wake → call → frequency words → end, return command."""
        self.p = CommandParser()
        self.p.process("talk spotter")
        self.p.process("call november romeo eight echo")
        self.p.process(f"frequency {freq_words}")
        return self.p.process("end")

    def test_decimal_mhz(self):
        result = self._parse_freq("fourteen decimal two one nine")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.frequency_khz, 14219.0)

    def test_no_decimal_khz(self):
        result = self._parse_freq("one four two one nine")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.frequency_khz, 14219.0)

    def test_compound_twenty_eight_decimal(self):
        result = self._parse_freq("twenty eight decimal five")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.frequency_khz, 28500.0)

    def test_compound_twenty_decimal(self):
        result = self._parse_freq("twenty decimal five")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.frequency_khz, 20500.0)

    def test_vhf_frequency(self):
        result = self._parse_freq("one four six five two zero")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result.frequency_khz, 146520.0)

    def test_unparseable(self):
        result = self._parse_freq("blah blah blah")
        # No valid frequency digits → freq stays 0 → invalid
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Module-level functions
# ---------------------------------------------------------------------------

class TestParseNatoCallsign(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(parse_nato_callsign("november romeo eight echo"), "NR8E")

    def test_empty(self):
        self.assertEqual(parse_nato_callsign(""), "")

    def test_garbage(self):
        self.assertEqual(parse_nato_callsign("hello world"), "")

    def test_mixed_valid_invalid(self):
        self.assertEqual(parse_nato_callsign("november blurb romeo"), "NR")

    def test_single_chars(self):
        self.assertEqual(parse_nato_callsign("A 1 B"), "A1B")

    def test_slash_in_callsign(self):
        self.assertEqual(
            parse_nato_callsign("victor papa two echo slash whiskey one alpha whiskey"),
            "VP2E/W1AW",
        )

    def test_stroke_in_callsign(self):
        self.assertEqual(
            parse_nato_callsign("whiskey one alpha whiskey stroke papa"),
            "W1AW/P",
        )


class TestParseFrequencyText(unittest.TestCase):
    def test_mhz_with_decimal(self):
        self.assertAlmostEqual(parse_frequency_text("one four point two five"), 14250.0)

    def test_khz_direct(self):
        self.assertAlmostEqual(parse_frequency_text("one four two five zero"), 14250.0)

    def test_empty(self):
        self.assertIsNone(parse_frequency_text(""))

    def test_garbage(self):
        self.assertIsNone(parse_frequency_text("hello world"))

    def test_vhf(self):
        self.assertAlmostEqual(parse_frequency_text("one four six five two zero"), 146520.0)


# ---------------------------------------------------------------------------
# SpotCommand
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Tricky edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):
    def test_complete_as_end_keyword(self):
        p = CommandParser()
        p.process("talk spotter")
        p.process("call november romeo eight echo frequency one four two one nine")
        result = p.process("complete")
        self.assertIsNotNone(result)
        self.assertEqual(result.callsign, "NR8E")
        self.assertEqual(result.frequency_khz, 14219.0)

    def test_call_sign_split_across_utterances(self):
        """'call' in one utterance, 'sign' starting the next — won't merge."""
        p = CommandParser()
        p.process("talk spotter")
        p.process("call")
        p.process("sign november romeo eight echo")
        p.process("frequency one four two one nine")
        result = p.process("end")
        # "sign" doesn't merge cross-utterance; it becomes data under "call".
        # "sign" is not NATO, so it's dropped. Callsign = NR8E still works
        # because the words after "sign" are valid NATO.
        self.assertIsNotNone(result)
        self.assertEqual(result.callsign, "NR8E")

    def test_multiple_decimals_in_frequency(self):
        """'one four point two point five' → '14.2.5' → ValueError → no freq."""
        p = CommandParser()
        p.process("talk spotter")
        p.process("call november romeo eight echo")
        p.process("frequency one four point two point five")
        result = p.process("end")
        self.assertIsNone(result)

    def test_both_network_keywords(self):
        """Last network keyword wins (dict dedup by position)."""
        p = CommandParser()
        p.process("talk spotter")
        p.process("call november romeo eight echo")
        p.process("parks kilo dash nine nine nine nine")
        p.process("summits whiskey four charlie slash charlie mike dash zero zero one")
        p.process("frequency one four two one nine")
        result = p.process("end")
        self.assertIsNotNone(result)
        self.assertEqual(result.network, "sota")
        self.assertEqual(result.network_id, "W4C/CM-001")

    def test_recursive_wake_phrase(self):
        """Double wake phrase in one utterance — second reset wins."""
        p = CommandParser()
        result = p.process(
            "talk spotter talk spotter call november romeo eight echo "
            "frequency one four two one nine end"
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.callsign, "NR8E")
        self.assertEqual(result.frequency_khz, 14219.0)

    def test_callsign_with_slash(self):
        """Callsign with slash: VP2E/W1AW."""
        p = CommandParser()
        p.process("talk spotter")
        p.process("call victor papa two echo slash whiskey one alpha whiskey")
        p.process("frequency one four two one nine")
        result = p.process("end")
        self.assertIsNotNone(result)
        self.assertEqual(result.callsign, "VP2E/W1AW")

    def test_callsign_with_stroke(self):
        """'stroke' works same as 'slash'."""
        p = CommandParser()
        p.process("talk spotter")
        p.process("call victor papa two echo stroke whiskey one alpha whiskey")
        p.process("frequency one four two one nine")
        result = p.process("end")
        self.assertIsNotNone(result)
        self.assertEqual(result.callsign, "VP2E/W1AW")

    def test_callsign_with_multiple_slashes(self):
        """Callsign with two slashes: W1AW/VP2/P."""
        p = CommandParser()
        p.process("talk spotter")
        p.process("call whiskey one alpha whiskey slash victor papa two slash papa")
        p.process("frequency one four two one nine")
        result = p.process("end")
        self.assertIsNotNone(result)
        self.assertEqual(result.callsign, "W1AW/VP2/P")

    def test_session_timeout_inside_process(self):
        """Session timeout fires inside process() when drip-fed over 60s."""
        p = CommandParser(session_timeout=0.1)
        p.process("talk spotter")
        p.process("call november romeo eight echo")
        time.sleep(0.15)
        # This process() call should trigger the session timeout path
        # inside process() itself (not check_timeout)
        p.process("frequency one four two one nine")
        # Parser should have reset after the timeout finalization
        self.assertEqual(p.state, CommandState.IDLE)


class TestSpotCommand(unittest.TestCase):
    def test_is_valid_both_fields(self):
        cmd = SpotCommand(callsign="NR8E", frequency_khz=14219.0)
        self.assertTrue(cmd.is_valid())

    def test_is_valid_no_callsign(self):
        cmd = SpotCommand(frequency_khz=14219.0)
        self.assertFalse(cmd.is_valid())

    def test_is_valid_no_frequency(self):
        cmd = SpotCommand(callsign="NR8E")
        self.assertFalse(cmd.is_valid())

    def test_is_valid_empty(self):
        cmd = SpotCommand()
        self.assertFalse(cmd.is_valid())

    def test_str_basic(self):
        cmd = SpotCommand(callsign="NR8E", frequency_khz=14219.0)
        self.assertIn("NR8E", str(cmd))
        self.assertIn("14219.0", str(cmd))

    def test_str_with_network(self):
        cmd = SpotCommand(callsign="NR8E", frequency_khz=14219.0, network="pota", network_id="K-1234")
        s = str(cmd)
        self.assertIn("POTA", s)
        self.assertIn("K-1234", s)


if __name__ == '__main__':
    unittest.main()
