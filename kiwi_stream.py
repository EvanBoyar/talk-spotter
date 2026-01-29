#!/usr/bin/env python3
"""
Talk Spotter - KiwiSDR Audio Streaming and Transcription

Streams audio from a KiwiSDR receiver and transcribes using Vosk.
"""

import argparse
import json
import logging
import os
import signal
import struct
import sys
import threading
import time
from pathlib import Path
from queue import Queue, Empty

import numpy as np
import yaml
from vosk import Model, KaldiRecognizer

# Add kiwiclient to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'kiwiclient'))
from kiwi import KiwiSDRStream


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
    def kiwi_host(self) -> str:
        return self.data.get("kiwisdr", {}).get("host", "")

    @property
    def kiwi_port(self) -> int:
        return self.data.get("kiwisdr", {}).get("port", 8073)

    @property
    def frequency(self) -> float:
        return self.data.get("kiwisdr", {}).get("frequency", 14.230)

    @property
    def mode(self) -> str:
        return self.data.get("kiwisdr", {}).get("mode", "usb")

    @property
    def vosk_model_path(self) -> str:
        return self.data.get("vosk", {}).get("model_path", "vosk-model-small-en-us-0.15")

    @property
    def vosk_sample_rate(self) -> int:
        return self.data.get("vosk", {}).get("sample_rate", 16000)

    @property
    def keywords(self) -> list:
        return self.data.get("keywords", [])


def resample_audio(samples: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    """Resample audio using linear interpolation."""
    if from_rate == to_rate:
        return samples

    n = len(samples)
    ratio = to_rate / from_rate
    out_len = int(n * ratio)

    if out_len == 0:
        return np.array([], dtype=np.int16)

    xa = np.arange(out_len) / ratio
    xp = np.arange(n)
    resampled = np.round(np.interp(xa, xp, samples)).astype(np.int16)

    return resampled


class TalkSpotterKiwiClient(KiwiSDRStream):
    """KiwiSDR client that pipes audio to a queue for transcription."""

    def __init__(self, options, audio_queue: Queue):
        super().__init__()
        self._options = options
        self._audio_queue = audio_queue
        self._type = 'SND'  # Sound stream type
        self._freq = options.frequency
        self._start_ts = None
        self._start_time = None

    def _setup_rx_params(self):
        """Set up receiver parameters after connection."""
        self.set_name(self._options.user)
        mod = self._options.modulation
        lp = self._options.lp_cut
        hp = self._options.hp_cut
        self.set_mod(mod, lp, hp, self._freq)
        self.set_agc(on=True)

    def _process_audio_samples(self, seq, samples, rssi, fmt):
        """Called when audio samples are received."""
        # Skip first few packets which may have startup artifacts
        if seq < 2:
            return
        # samples is a numpy array of int16
        if len(samples) > 0:
            self._audio_queue.put((samples, self._sample_rate))

    def _on_sample_rate_change(self):
        """Called when sample rate is established."""
        logging.info(f"KiwiSDR sample rate: {self._sample_rate} Hz")


class KiwiOptions:
    """Options object compatible with kiwiclient."""

    def __init__(self, host, port, freq, mode):
        self.server_host = host
        self.server_port = port
        self.frequency = freq
        self.modulation = mode

        # Required defaults
        self.user = 'TalkSpotter'
        self.password = ''
        self.tlimit_password = ''
        self.ws_timestamp = int(time.time())
        self.socket_timeout = 10
        self.wideband = False
        self.admin = False
        self.nolocal = False

        # Audio settings
        self.lp_cut = None  # Low pass filter
        self.hp_cut = None  # High pass filter
        self.freq_offset = 0
        self.agc_gain = None
        self.agc_yaml = None
        self.no_api = False
        self.de_emp = False
        self.raw = False
        self.nb = False
        self.nb_gate = 100
        self.nb_thresh = 50

        # Not used but required
        self.is_kiwi_tdoa = False
        self.is_kiwi_wav = False
        self.dir = None
        self.fn = None
        self.station = None
        self.filename = ''
        self.test_mode = False
        self.sq_thresh = None
        self.scan_yaml = None
        self.resample = 0
        self.freq_pbc = None
        self.S_meter = -1
        self.stats = False
        self.no_api = False
        self.tstamp = False
        self.idx = 0
        self.tlimit = None
        self.sound = True
        self.sdt = 0
        self.netcat = False
        self.multiple_connections = False
        self.nb_test = False
        self.wf_cal = None
        self.camp_allow_1ch = False
        self.ADC_OV = False

        # Camping
        self.camp_chan = -1


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
        """Process audio data and return (final_text, partial_text)."""
        if self.recognizer.AcceptWaveform(audio_data):
            result = json.loads(self.recognizer.Result())
            return result.get("text", ""), ""
        else:
            partial = json.loads(self.recognizer.PartialResult())
            return "", partial.get("partial", "")


def detect_keywords(text: str, keywords: list) -> list:
    """Check if any keywords are present in the text. Returns list of found keywords."""
    if not text or not keywords:
        return []
    text_lower = text.lower()
    return [kw for kw in keywords if kw.lower() in text_lower]


def run_kiwi_client(client, stop_event):
    """Run the KiwiSDR client in a thread."""
    try:
        while not stop_event.is_set():
            client.run()
    except Exception as e:
        logging.error(f"KiwiSDR client error: {e}")
    finally:
        try:
            client.close()
        except:
            pass


def main():
    parser = argparse.ArgumentParser(
        description="Stream audio from KiwiSDR and transcribe using Vosk"
    )
    parser.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="Path to configuration file"
    )
    parser.add_argument(
        "--host", "-s",
        help="KiwiSDR hostname (overrides config)"
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=8073,
        help="KiwiSDR port (default: 8073)"
    )
    parser.add_argument(
        "--freq", "-f",
        type=float,
        help="Frequency in kHz (overrides config)"
    )
    parser.add_argument(
        "--mode", "-m",
        choices=["usb", "lsb", "am", "cw", "nbfm"],
        help="Demodulation mode (overrides config)"
    )
    parser.add_argument(
        "--model",
        help="Path to Vosk model (overrides config)"
    )
    parser.add_argument(
        "--keywords", "-k",
        nargs="+",
        help="Keywords to detect (overrides config)"
    )
    parser.add_argument(
        "--debug", "-d",
        action="store_true",
        help="Enable debug logging"
    )

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(level=log_level, format='%(asctime)s %(levelname)s: %(message)s')

    # Load configuration
    config = Config(args.config)

    # Get parameters (CLI overrides config)
    host = args.host or config.kiwi_host
    port = args.port or config.kiwi_port
    freq = args.freq or config.frequency
    mode = args.mode or config.mode
    model_path = args.model or config.vosk_model_path
    vosk_rate = config.vosk_sample_rate
    keywords = args.keywords or config.keywords

    if not host:
        print("Error: KiwiSDR host is required. Use --host or set in config.yaml")
        print("Find public KiwiSDRs at: http://kiwisdr.com/public/")
        sys.exit(1)

    # Convert frequency to kHz if given in MHz
    if freq < 100:
        freq = freq * 1000  # Convert MHz to kHz

    print(f"Connecting to KiwiSDR: {host}:{port}")
    print(f"Frequency: {freq} kHz, Mode: {mode.upper()}")

    # Initialize components
    audio_queue = Queue()
    kiwi_options = KiwiOptions(host, port, freq, mode)
    kiwi_client = TalkSpotterKiwiClient(kiwi_options, audio_queue)
    transcriber = Transcriber(model_path, vosk_rate)

    # Graceful shutdown
    stop_event = threading.Event()

    def signal_handler(sig, frame):
        print("\nShutting down...")
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # Start transcriber
        transcriber.start()

        # Connect to KiwiSDR
        kiwi_client.connect(host, port)
        kiwi_client.open()

        # Start client thread
        client_thread = threading.Thread(
            target=run_kiwi_client,
            args=(kiwi_client, stop_event),
            daemon=True
        )
        client_thread.start()

        print("\n" + "=" * 50)
        print("Transcription started. Press Ctrl+C to stop.")
        if keywords:
            print(f"Watching for keywords: {', '.join(keywords)}")
        print("=" * 50 + "\n")

        last_partial = ""
        audio_buffer = b""
        kiwi_sample_rate = 12000  # Updated when we receive samples
        target_chunk_size = 8000  # ~0.25 seconds at 16kHz
        chunks_received = 0

        while not stop_event.is_set():
            try:
                samples, kiwi_sample_rate = audio_queue.get(timeout=0.5)
                chunks_received += 1

                if chunks_received == 1:
                    print(f"First audio chunk: {len(samples)} samples at {kiwi_sample_rate} Hz")
                if chunks_received % 100 == 0:
                    print(f"Chunks received: {chunks_received}")

                # Resample to Vosk's expected rate
                resampled = resample_audio(samples, kiwi_sample_rate, vosk_rate)

                # Convert to bytes
                audio_bytes = resampled.tobytes()
                audio_buffer += audio_bytes

                # Process when we have enough data
                if len(audio_buffer) >= target_chunk_size:
                    final, partial = transcriber.process_audio(audio_buffer)
                    audio_buffer = b""

                    if final:
                        found = detect_keywords(final, keywords)
                        if found:
                            print(f"[MATCH] {final}  <-- {', '.join(found)}")
                        else:
                            print(f"[FINAL] {final}")

                    if partial and partial != last_partial:
                        print(f"[...] {partial}", end="\r", flush=True)
                        last_partial = partial

            except Empty:
                continue

    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Error: {e}")
        if args.debug:
            raise
        sys.exit(1)
    finally:
        stop_event.set()
        try:
            kiwi_client.close()
        except:
            pass
        print("Cleanup complete.")


if __name__ == "__main__":
    main()
