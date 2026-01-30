#!/usr/bin/env python3
"""
Talk Spotter - Voice-activated amateur radio spotting tool.

Listens to radio audio streams, transcribes speech, detects keywords,
and can push spots to DX Cluster and POTA/SOTA networks.
"""

import argparse
import logging
import signal
import sys
import time
import wave
from pathlib import Path

import yaml

from transcription import Transcriber, detect_keywords
from sources import KiwiSDRSource, RTLSDRSource
from dx_cluster import DXCluster
from pota_spotter import POTASpotter
from sota_spotter import SOTASpotter, SOTAAuth
from command_parser import CommandParser, SpotCommand


class Config:
    """Configuration manager for Talk Spotter."""

    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = Path(config_path)
        self.data = self._load_config()

    def _load_config(self) -> dict:
        if self.config_path.exists():
            with open(self.config_path) as f:
                return yaml.safe_load(f) or {}
        return {}

    @property
    def callsign(self) -> str:
        """Get user's callsign for spot posting."""
        return self.data.get("callsign", "")

    @property
    def radio(self) -> str:
        """Get selected radio source type."""
        return self.data.get("radio", "kiwisdr")

    @property
    def kiwisdr(self) -> dict:
        """Get KiwiSDR configuration."""
        return self.data.get("kiwisdr", {})

    @property
    def rtl_sdr(self) -> dict:
        """Get RTL-SDR configuration."""
        return self.data.get("rtl_sdr", {})

    @property
    def vosk(self) -> dict:
        """Get Vosk configuration."""
        return self.data.get("vosk", {})

    @property
    def dx_cluster(self) -> dict:
        """Get DX Cluster configuration."""
        return self.data.get("dx_cluster", {})

    @property
    def pota(self) -> dict:
        """Get POTA configuration."""
        return self.data.get("pota", {})

    @property
    def sota(self) -> dict:
        """Get SOTA configuration."""
        return self.data.get("sota", {})

    @property
    def keywords(self) -> list:
        """Get keywords to detect."""
        return self.data.get("keywords", [])


def create_source(config: Config):
    """Create the appropriate audio source based on configuration."""
    radio = config.radio.lower()

    if radio == "kiwisdr":
        return KiwiSDRSource(config.kiwisdr)
    elif radio == "rtl_sdr":
        return RTLSDRSource(config.rtl_sdr)
    else:
        raise ValueError(f"Unknown radio type: {radio}")


def main():
    parser = argparse.ArgumentParser(
        description="Talk Spotter - Voice-activated amateur radio spotting"
    )
    parser.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="Path to configuration file (default: config.yaml)"
    )
    parser.add_argument(
        "--radio", "-r",
        choices=["kiwisdr", "rtl_sdr"],
        help="Radio source (overrides config)"
    )
    parser.add_argument(
        "--debug", "-d",
        action="store_true",
        help="Enable debug logging"
    )
    parser.add_argument(
        "--save-wav",
        metavar="FILE",
        help="Save received audio to WAV file for debugging"
    )
    parser.add_argument(
        "--test-file",
        metavar="FILE",
        help="Test transcription with a WAV file (no radio needed)"
    )
    parser.add_argument(
        "--spot-mode",
        action="store_true",
        help="Enable voice command parsing and spot posting"
    )
    parser.add_argument(
        "--no-post",
        action="store_true",
        help="Parse commands but don't actually post spots (for testing)"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Live transcription mode - clean display of speech as it's heard"
    )
    parser.add_argument(
        "--sota-login",
        action="store_true",
        help="Login to SOTA (one-time setup for spot posting)"
    )
    parser.add_argument(
        "--sota-logout",
        action="store_true",
        help="Logout from SOTA (clear stored tokens)"
    )
    parser.add_argument(
        "--sota-status",
        action="store_true",
        help="Check SOTA authentication status"
    )

    args = parser.parse_args()

    # Handle SOTA authentication commands (no radio needed)
    if args.sota_login:
        auth = SOTAAuth()
        success = auth.device_login()
        sys.exit(0 if success else 1)

    if args.sota_logout:
        auth = SOTAAuth()
        auth.logout()
        sys.exit(0)

    if args.sota_status:
        auth = SOTAAuth()
        if auth.is_authenticated:
            if auth.ensure_valid_token():
                print("SOTA: Authenticated (tokens valid)")
            else:
                print("SOTA: Tokens expired - run --sota-login to re-authenticate")
        else:
            print("SOTA: Not authenticated - run --sota-login to authenticate")
        sys.exit(0)

    # Setup logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s %(levelname)s: %(message)s'
    )

    # Load configuration
    config = Config(args.config)

    # Override radio if specified
    if args.radio:
        config.data["radio"] = args.radio

    # Get Vosk settings
    vosk_config = config.vosk
    model_path = vosk_config.get("model_path", "vosk-model-small-en-us-0.15")
    sample_rate = vosk_config.get("sample_rate", 16000)

    # Get keywords
    keywords = config.keywords
    if keywords:
        print(f"Watching for keywords: {', '.join(keywords)}")

    # Test file mode - transcribe a WAV file and exit
    if args.test_file:
        print(f"Testing transcription with: {args.test_file}")
        transcriber = Transcriber(model_path, sample_rate)
        transcriber.start()

        with wave.open(args.test_file, 'rb') as wf:
            if wf.getnchannels() != 1:
                print("Warning: WAV file is not mono, results may be poor")
            if wf.getframerate() != sample_rate:
                print(f"Warning: WAV file is {wf.getframerate()}Hz, expected {sample_rate}Hz")

            print(f"Reading {wf.getnframes()} frames...")
            chunk_size = 4000  # Process in chunks
            while True:
                data = wf.readframes(chunk_size)
                if len(data) == 0:
                    break
                final, partial = transcriber.process_audio(data)
                if final:
                    found = detect_keywords(final, keywords)
                    if found:
                        print(f"[MATCH] {final}  <-- {', '.join(found)}")
                    else:
                        print(f"[FINAL] {final}")
                elif partial:
                    print(f"[...] {partial}", end="\r", flush=True)

            # Get any remaining text
            final = transcriber.get_final_result()
            if final:
                found = detect_keywords(final, keywords)
                if found:
                    print(f"[MATCH] {final}  <-- {', '.join(found)}")
                else:
                    print(f"[FINAL] {final}")

        print("\nTest complete.")
        sys.exit(0)

    # Create transcriber
    transcriber = Transcriber(model_path, sample_rate)

    # Create command parser if spot mode enabled
    cmd_parser = None
    dx_cluster = None
    if args.spot_mode:
        cmd_parser = CommandParser(wake_phrase="talk spotter")
        print("Spot mode enabled - say 'talk spotter' to start a command")

        # Check callsign is configured
        if not args.no_post:
            if not config.callsign:
                print("Warning: No callsign in config - spots will not be posted")
            else:
                dx_host = config.dx_cluster.get('host')
                if dx_host:
                    print(f"Will post spots as {config.callsign} to {dx_host}")

    # Create audio source
    print(f"Radio source: {config.radio}")
    source = create_source(config)

    # Graceful shutdown
    stop_requested = False

    def signal_handler(_sig, _frame):
        nonlocal stop_requested
        print("\nShutting down...")
        stop_requested = True
        source.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # WAV file for saving audio
    wav_file = None
    if args.save_wav:
        wav_file = wave.open(args.save_wav, 'wb')
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        print(f"Saving audio to: {args.save_wav}")

    # Function to post a spot
    def post_spot(command: SpotCommand):
        """Post a spot to DX Cluster, POTA, and/or SOTA."""
        dx_config = config.dx_cluster
        pota_config = config.pota
        sota_config = config.sota
        callsign = config.callsign

        if not callsign:
            print("[SPOT] No callsign configured - cannot post")
            return False

        if args.no_post:
            spot_info = f"{command.callsign} on {command.frequency_khz:.1f} kHz"
            if command.network == "pota" and command.network_id:
                spot_info += f" (POTA {command.network_id})"
            elif command.network == "sota" and command.network_id:
                spot_info += f" (SOTA {command.network_id})"
            print(f"[SPOT] Would post: {spot_info}")
            return True

        # Check if this is a POTA spot
        if command.network == "pota":
            pota_enabled = pota_config.get('enabled', False)

            if not pota_enabled:
                print("[POTA] POTA spotting is disabled in config")
            elif not command.network_id:
                print("[POTA] No park reference provided - cannot post to POTA")
            else:
                print(f"[POTA] Posting: {command.callsign} at {command.network_id} on {command.frequency_khz:.1f} kHz")
                try:
                    spotter = POTASpotter(callsign)
                    result = spotter.post_spot(
                        activator=command.callsign,
                        frequency_khz=command.frequency_khz,
                        park_ref=command.network_id,
                        mode="SSB",
                        comments="Spotted via TalkSpotter"
                    )
                    if result["success"]:
                        print(f"[POTA] Posted successfully!")
                    else:
                        print(f"[POTA] Failed to post: {result.get('error', 'Unknown error')}")
                except Exception as e:
                    print(f"[POTA] Failed to post: {e}")

        # Check if this is a SOTA spot
        elif command.network == "sota":
            sota_enabled = sota_config.get('enabled', False)

            if not sota_enabled:
                print("[SOTA] SOTA spotting is disabled in config")
            elif not command.network_id:
                print("[SOTA] No summit reference provided - cannot post to SOTA")
            else:
                print(f"[SOTA] Posting: {command.callsign} at {command.network_id} on {command.frequency_khz:.1f} kHz")
                try:
                    auth = SOTAAuth()
                    if not auth.is_authenticated:
                        print("[SOTA] Not logged in - run with --sota-login first")
                    else:
                        spotter = SOTASpotter(callsign, auth)
                        result = spotter.post_spot(
                            activator=command.callsign,
                            frequency_khz=command.frequency_khz,
                            summit_ref=command.network_id,
                            mode="SSB",
                            comments="Spotted via TalkSpotter"
                        )
                        if result["success"]:
                            print(f"[SOTA] Posted successfully!")
                        else:
                            print(f"[SOTA] Failed to post: {result.get('error', 'Unknown error')}")
                except Exception as e:
                    print(f"[SOTA] Failed to post: {e}")

        # Post to DX Cluster if configured
        host = dx_config.get('host')
        port = dx_config.get('port')

        if not host or not port:
            logging.debug("DX Cluster not configured - skipping")
            return True

        # Build comment
        comment = "TalkSpotter"
        if command.network:
            comment += f" {command.network.upper()}"
            if command.network_id:
                comment += f" {command.network_id}"

        print(f"[SPOT] Posting to DX Cluster: {command.callsign} on {command.frequency_khz:.1f} kHz")
        try:
            with DXCluster(host, port, callsign) as cluster:
                response = cluster.spot(command.frequency_khz, command.callsign, comment)
                logging.debug(f"Cluster response: {response}")
                print(f"[SPOT] Posted successfully!")
                return True
        except Exception as e:
            print(f"[SPOT] Failed to post: {e}")
            return False

    # Audio processing state
    audio_buffer = b""
    last_partial = ""
    last_partial_len = [0]  # Track length for clearing line in live mode
    target_chunk_size = 8000  # ~0.25 seconds at 16kHz
    chunks_received = [0]

    def audio_callback(audio_samples):
        """Process incoming audio samples."""
        nonlocal audio_buffer, last_partial

        chunks_received[0] += 1
        if chunks_received[0] == 1 and not args.live:
            print(f"First audio chunk: {len(audio_samples)} samples")
        if chunks_received[0] % 100 == 0:
            logging.debug(f"Chunks received: {chunks_received[0]}")

        # Save to WAV if enabled
        if wav_file:
            wav_file.writeframes(audio_samples.tobytes())

        # Add to buffer
        audio_buffer += audio_samples.tobytes()

        # Process when we have enough data
        while len(audio_buffer) >= target_chunk_size:
            chunk = audio_buffer[:target_chunk_size]
            audio_buffer = audio_buffer[target_chunk_size:]

            final, partial = transcriber.process_audio(chunk)

            if args.live:
                # Live mode: clean display
                if final:
                    # Clear partial line and print final text
                    print("\r" + " " * last_partial_len[0] + "\r", end="")
                    print(final)
                    last_partial_len[0] = 0
                elif partial and partial != last_partial:
                    # Update partial in place
                    display = partial
                    # Clear previous and show new
                    print("\r" + " " * last_partial_len[0] + "\r" + display, end="", flush=True)
                    last_partial_len[0] = len(display)
                    last_partial = partial
            else:
                # Standard mode with labels
                if final:
                    found = detect_keywords(final, keywords)
                    if found:
                        print(f"[MATCH] {final}  <-- {', '.join(found)}")
                    else:
                        print(f"[FINAL] {final}")

                if partial and partial != last_partial:
                    print(f"[...] {partial}", end="\r", flush=True)
                    last_partial = partial

            # Voice command parsing (works in both modes)
            if final and cmd_parser:
                command = cmd_parser.process(final)
                if command and command.is_valid():
                    post_spot(command)

            # Feed partials to command parser for real-time feedback
            if partial and partial != last_partial and cmd_parser:
                cmd_parser.process(partial)

    try:
        # Start transcriber
        transcriber.start()

        # Start audio source
        source.start(audio_callback)

        if args.live:
            print("\nListening... (Ctrl+C to stop)\n")
        else:
            print("\n" + "=" * 50)
            print("Transcription started. Press Ctrl+C to stop.")
            if args.spot_mode:
                print("Say 'talk spotter' followed by:")
                print("  'call' + NATO phonetic callsign")
                print("  'frequency' + spoken frequency (e.g., 'one four point two five' or 'one four two five zero')")
                print("  'end' to post the spot")
            print("=" * 50 + "\n")

        # Main loop - check for timeout periodically
        while not stop_requested and source.is_running:
            time.sleep(1.0)  # Check every second

            # Check for command timeout (user went silent)
            if cmd_parser:
                command = cmd_parser.check_timeout()
                if command and command.is_valid():
                    post_spot(command)

    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Error: {e}")
        if args.debug:
            raise
        sys.exit(1)
    finally:
        source.stop()
        if wav_file:
            wav_file.close()
            print(f"Audio saved to: {args.save_wav}")
        print("Cleanup complete.")


if __name__ == "__main__":
    main()
