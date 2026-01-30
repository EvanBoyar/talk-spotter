# Talk Spotter

<p align="center">
  <img src="talkspotter.png" alt="Talk Spotter" width="128">
</p>

A voice-activated amateur radio spotting tool for Linux by Evan Boyar, [NR8E](https://www.qrz.com/db/NR8E). Talk Spotter listens to radio audio streams, transcribes speech on-device, and can post spots to the DX Cluster network (and in later revs POTA and SOTA) via voice commands. 

It is similar to but different from CW Skimmer by VE3NEA in several ways, and not just that it's open source. As the signal processing power needed to decode the human voice is greater than what is required for CW, it can only really decode audio from a single frequency & mode at a time. As a result, you will have to set the frequency & mode you'd like your TS instance to listen on ahead of time. A standard list of frequency/mode pairs for the US amateur bands is below.

## Features

- **Multiple audio sources**: RTL-SDR (local hardware) or KiwiSDR (remote). Rig support coming soon™
- **On-device transcription**: Uses Vosk for privacy-preserving speech-to-text
- **Voice command parsing**: Say "talk spotter" followed by callsign and frequency to post a spot (see instructions for exact directions)
- **DX Cluster integration**: Posts spots to the DX Cluster network
- **Keyword detection**: Highlight specific words/phrases in transcription output
- **Designed for Raspberry Pi**: Lightweight, minimal dependencies

## Requirements

- Python 3.8+
- Linux (tested on Ubuntu)
- For RTL-SDR: RTL-SDR dongle (e.g., RTL-SDR Blog V3)
- For KiwiSDR: Internet connection

## Installation

### Quick install (copy-paste)

```bash
git clone https://github.com/yourusername/talk-spotter.git && cd talk-spotter && python3 -m venv venv && venv/bin/pip install -r requirements.txt && wget -q https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip && unzip -q vosk-model-small-en-us-0.15.zip && rm vosk-model-small-en-us-0.15.zip && git clone https://github.com/jks-prv/kiwiclient.git
```

Then activate the venv and run: `source venv/bin/activate && python talk_spotter.py`

### Step-by-step

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/talk-spotter.git
   cd talk-spotter
   ```

2. **Create and activate a virtual environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install Python dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Download the Vosk speech recognition model**
   ```bash
   wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
   unzip vosk-model-small-en-us-0.15.zip
   ```

5. **Install kiwiclient** (for KiwiSDR support)
   ```bash
   git clone https://github.com/jks-prv/kiwiclient.git
   ```

6. **(RTL-SDR only) Blacklist kernel modules**

   Create `/etc/modprobe.d/blacklist-rtlsdr.conf`:
   ```
   blacklist dvb_usb_rtl28xxu
   blacklist rtl2832_sdr
   blacklist rtl2832
   ```
   Then reboot or unload the modules manually.

## Configuration

Edit `config.yaml` to configure your setup:

```yaml
# Select radio source: kiwisdr or rtl_sdr
radio: "rtl_sdr"

# KiwiSDR settings
kiwisdr:
  host: "22001.proxy.kiwisdr.com"
  port: 8073
  frequency: 7218    # kHz
  mode: "lsb"        # usb, lsb, am, cw, nbfm

# RTL-SDR settings
rtl_sdr:
  frequency: 147.42  # MHz
  mode: "fm"         # fm, nbfm, usb, lsb, am
  gain: "auto"
  direct_sampling: 0 # 0=off, 2=Q-branch (for HF)
  agc: false         # Enable for HF direct sampling
  sample_rate: 256000

# DX Cluster settings
dx_cluster:
  host: "dxc.ve7cc.net"
  port: 23
  callsign: "N0CALL"  # Your callsign

# Keywords to highlight
keywords:
  - "talk spotter"
  - "cq"
```

## Usage

### Basic usage

Run with settings from `config.yaml`:
```bash
python talk_spotter.py
```

### Override radio source

Use `--radio` to override the config file:
```bash
python talk_spotter.py --radio kiwisdr
python talk_spotter.py --radio rtl_sdr
```

### HF with RTL-SDR

For HF SSB reception, set these options in `config.yaml`:
```yaml
rtl_sdr:
  frequency: 7.205
  mode: "usb"
  direct_sampling: 2
  agc: true
  sample_rate: 960000
```

### Using KiwiSDR

```bash
python talk_spotter.py --radio kiwisdr
```

### Voice command mode

Enable spot posting via voice commands:
```bash
python talk_spotter.py --spot-mode
```

**Voice command format:**
1. Say "talk spotter" (wake phrase)
2. Say "call" followed by the callsign in NATO phonetics (e.g., "whiskey one alpha whiskey")
3. Say "frequency" followed by the frequency in MHz (e.g., "one four point two one nine" for 14.219)
4. Say "end" to post the spot

Example: "talk spotter call whiskey one alpha whiskey frequency one four point two one nine end"

### Test mode (no posting)

Parse voice commands without actually posting:
```bash
python talk_spotter.py --spot-mode --no-post
```

### Debug audio

Save received audio to a WAV file:
```bash
python talk_spotter.py --save-wav debug.wav
```

Test transcription with a pre-recorded file:
```bash
python talk_spotter.py --test-file recording.wav
```

### All options

```
usage: talk_spotter.py [-h] [--config CONFIG] [--radio {kiwisdr,rtl_sdr}]
                       [--debug] [--save-wav FILE] [--test-file FILE]
                       [--spot-mode] [--no-post]

options:
  -h, --help            show this help message and exit
  --config, -c CONFIG   Path to configuration file (default: config.yaml)
  --radio, -r {kiwisdr,rtl_sdr}
                        Radio source (overrides config)
  --debug, -d           Enable debug logging
  --save-wav FILE       Save received audio to WAV file for debugging
  --test-file FILE      Test transcription with a WAV file (no radio needed)
  --spot-mode           Enable voice command parsing and spot posting
  --no-post             Parse commands but don't actually post spots
```

## Standalone scripts

These scripts can be used independently for testing specific functionality:

- `kiwi_stream.py` - Stream and transcribe from a KiwiSDR
- `rtl_stream.py` - Stream and transcribe from an RTL-SDR
- `dx_cluster.py` - Test DX Cluster connectivity

## Troubleshooting

### RTL-SDR not detected

Make sure the DVB-T kernel modules are blacklisted (see Installation step 6).

### "PLL not locked" warning

This is benign with pyrtlsdr. Audio still works correctly.

### HF reception is quiet

Enable hardware AGC (`agc: true`) and use direct sampling (`direct_sampling: 2`) for HF.

### Poor transcription accuracy

- Ensure audio is clear (check with `--save-wav`)
- Try a larger Vosk model for better accuracy
- Speak clearly and use standard phonetics for callsigns

## License

MIT

Copyright 2026 Evan Boyar

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the “Software”), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.