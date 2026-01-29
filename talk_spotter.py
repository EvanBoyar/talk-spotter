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
from pathlib import Path

import yaml

from transcription import Transcriber, detect_keywords
from sources import KiwiSDRSource, RTLSDRSource
# from dx_cluster import DXCluster  # TODO: integrate spot posting


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

    # Create transcriber
    transcriber = Transcriber(model_path, sample_rate)

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

        # Add to buffer
        audio_buffer += audio_samples.tobytes()

        # Process when we have enough data
        while len(audio_buffer) >= target_chunk_size:
            chunk = audio_buffer[:target_chunk_size]
            audio_buffer = audio_buffer[target_chunk_size:]

            final, partial = transcriber.process_audio(chunk)

            if final:
                found = detect_keywords(final, keywords)
                if found:
                    print(f"[MATCH] {final}  <-- {', '.join(found)}")
                else:
                    print(f"[FINAL] {final}")

            if partial and partial != last_partial:
                print(f"[...] {partial}", end="\r", flush=True)
                last_partial = partial

    try:
        # Start transcriber
        transcriber.start()

        # Start audio source
        source.start(audio_callback)

        print("\n" + "=" * 50)
        print("Transcription started. Press Ctrl+C to stop.")
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
        print("Cleanup complete.")


if __name__ == "__main__":
    main()
