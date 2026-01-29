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
import wave
from pathlib import Path

import yaml

from transcription import Transcriber, detect_keywords
from sources import KiwiSDRSource, RTLSDRSource
from dx_cluster import DXCluster
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

    args = parser.parse_args()

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

        # Setup DX cluster connection info
        dx_config = config.dx_cluster
        if not args.no_post:
            if not dx_config.get('callsign'):
                print("Warning: No callsign in config - spots will not be posted")
            else:
                print(f"Will post spots as {dx_config['callsign']} to {dx_config.get('host', 'dxc.ve7cc.net')}")

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
        """Post a spot to DX Cluster."""
        dx_config = config.dx_cluster
        callsign = dx_config.get('callsign', '')

        if not callsign:
            print("[SPOT] No callsign configured - cannot post")
            return False

        if args.no_post:
            print(f"[SPOT] Would post: {command.callsign} on {command.frequency_khz:.1f} kHz")
            return True

        host = dx_config.get('host', 'dxc.ve7cc.net')
        port = dx_config.get('port', 23)

        # Build comment
        comment = "TalkSpotter"
        if command.network:
            comment += f" {command.network.upper()}"
            if command.network_id:
                comment += f" {command.network_id}"

        print(f"[SPOT] Posting: {command.callsign} on {command.frequency_khz:.1f} kHz")
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
    target_chunk_size = 8000  # ~0.25 seconds at 16kHz
    chunks_received = [0]

    def audio_callback(audio_samples):
        """Process incoming audio samples."""
        nonlocal audio_buffer, last_partial

        chunks_received[0] += 1
        if chunks_received[0] == 1:
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

            if final:
                # Standard keyword detection
                found = detect_keywords(final, keywords)
                if found:
                    print(f"[MATCH] {final}  <-- {', '.join(found)}")
                else:
                    print(f"[FINAL] {final}")

                # Voice command parsing if enabled
                if cmd_parser:
                    command = cmd_parser.process(final)
                    if command and command.is_valid():
                        post_spot(command)

            if partial and partial != last_partial:
                print(f"[...] {partial}", end="\r", flush=True)
                last_partial = partial

                # Also feed partials to command parser for real-time feedback
                if cmd_parser:
                    cmd_parser.process(partial)

    try:
        # Start transcriber
        transcriber.start()

        # Start audio source
        source.start(audio_callback)

        print("\n" + "=" * 50)
        print("Transcription started. Press Ctrl+C to stop.")
        if args.spot_mode:
            print("Say 'talk spotter' followed by:")
            print("  'call' + NATO phonetic callsign")
            print("  'frequency' + spoken MHz (e.g., 'fourteen two five zero')")
            print("  'end' to post the spot")
        print("=" * 50 + "\n")

        # Wait for stop signal
        while not stop_requested and source.is_running:
            signal.pause()

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
