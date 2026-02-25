# Talk Spotter

<p align="center">
  <img src="talkspotter.png" alt="Talk Spotter" width="128">
</p>

A voice-activated amateur radio spotting tool for Linux by Evan Boyar, [NR8E](https://www.qrz.com/db/NR8E). Talk Spotter listens to radio audio streams, transcribes speech on-device, and can post spots to the DX Cluster network and POTA via voice commands.

It is similar to but different from CW Skimmer by VE3NEA in several ways, and not just that it's open source. As the signal processing power needed to decode the human voice is greater than what is required for CW, it can only really decode audio from a single frequency & mode at a time. As a result, you will have to set the frequency & mode you'd like your TS instance to listen on ahead of time. A standard list of frequency/mode pairs for the US amateur bands is below in the Band plan section.

I suggest you set it and forget it on a Raspberry Pi. I've tested it on a 3 B+.

## Features

- **Multiple audio sources**: RTL-SDR (local hardware) or KiwiSDR (remote). Rig support coming soon™
- **On-device transcription**: Uses Vosk for $0 speech-to-text
- **Voice command parsing**: Say "talk spotter" followed by callsign and frequency to post a spot (see instructions for exact directions)
- **DX Cluster integration**: Posts spots to the DX Cluster network
- **POTA integration**: Posts spots directly to Parks on the Air
- **SOTA integration**: Posts spots to Summits on the Air (OAuth authenticated), coming soon™
- **Keyword detection**: Highlight specific words/phrases in transcription output
- **Designed for Raspberry Pi**: Lightweight, minimal dependencies

## Band plan
As Talk Spotter is intended to be used by more than just those who have set up listening nodes, let's try to stick to these frequencies and modes. Send me a PR if you've noticed an issue with one of these.

|Band (m)|Frequency (kHz)|Mode|
|--------|---------------|----|
|40|7278|lsb|
|20|14278|usb|
|10|28578|usb|
|2|147578|nbfm|
|70|444578|nbfm|

## Requirements

- Python 3.8+
- Linux
- For RTL-SDR: RTL-SDR dongle (e.g., RTL-SDR Blog V3)
- For KiwiSDR: Internet connection

## Installation

### Quick install (copy-paste)

```bash
git clone https://github.com/EvanBoyar/talk-spotter.git && cd talk-spotter && python3 -m venv venv && venv/bin/pip install -r requirements.txt && wget -q https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip && unzip -q vosk-model-small-en-us-0.15.zip && rm vosk-model-small-en-us-0.15.zip && git clone https://github.com/jks-prv/kiwiclient.git
```

Then activate the venv and run: `source venv/bin/activate && python talk_spotter.py`

### Step-by-step install

1. **Clone the repository**
   ```bash
   git clone https://github.com/EvanBoyar/talk-spotter.git
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

Edit `config.yaml` to configure your setup. It's designed to be pretty human-readable.

**For HF SSB reception with the RTL-SDR**, you'll need to set "direct sampling: 2", which means we're, uh, directly sampling the Q branch, which is what you should use for HF. Use "direct sampling: 0" for UHF/VHF.

**SOTA Setup:** SOTA requires one-time authentication. Run `venv/bin/python talk_spotter.py --sota-login` and follow the instructions to log in via your browser. Tokens are stored locally and auto-refresh, so you only need to do this once.

## Usage

**Note:** All commands below assume you're in the `talk-spotter` directory. Use `venv/bin/python` to run with the virtual environment's Python (no need to activate the venv first).

### Basic usage

Run with settings from `config.yaml`:
```bash
venv/bin/python talk_spotter.py
```

### Override radio source

Use `--radio` to override the config file:
```bash
venv/bin/python talk_spotter.py --radio kiwisdr
venv/bin/python talk_spotter.py --radio rtl_sdr
```

### Using KiwiSDR

```bash
venv/bin/python talk_spotter.py --radio kiwisdr
```

### Voice command mode

Enable spot posting via voice commands:
```bash
venv/bin/python talk_spotter.py --spot-mode
```

**Voice command format:**
1. Say "talk spotter" (wake phrase)
2. Say "call" followed by the callsign in NATO phonetics (e.g., "whiskey one alpha whiskey")
3. (Optional) Say "parks" for POTA or "summits" for SOTA, followed by the reference (e.g., "kilo dash one two three four" for K-1234, or "whiskey four charlie slash charlie mike dash zero zero one" for W4C/CM-001)
4. Say "frequency" followed by the frequency (e.g., "one four point two one nine" for 14219 kHz, or "one four two one nine" for 14219 kHz)
5. Say "end" to post the spot (or wait 30 seconds for auto-complete)

**Examples:**

Basic DX Cluster spot:
```
"talk spotter call whiskey one alpha whiskey frequency one four point two one nine end"
```

POTA spot (posts to both POTA and DX Cluster):
```
"talk spotter call whiskey one alpha whiskey parks kilo dash one two three four frequency one four point two one nine end"
```

SOTA spot (posts to both SOTA and DX Cluster):
```
"talk spotter call whiskey one alpha whiskey summits whiskey four charlie slash charlie mike dash zero zero one frequency one four point two one nine end"
```

**Note:** Frequencies with a decimal point are interpreted as MHz and converted to kHz internally. Frequencies without a decimal (like "one four two one nine") are interpreted as kHz directly. If you don't say "end", the command will auto-complete after 30 seconds if a valid callsign and frequency were parsed. Saying "talk spotter" again will restart the command.

POTA spots require the park reference (e.g., K-1234). Speak it as "kilo dash one two three four" using NATO phonetics for letters and spoken numbers for digits.

### Test mode (no posting)

Parse voice commands without actually posting:
```bash
venv/bin/python talk_spotter.py --spot-mode --no-post
```

### Live transcription

For a clean, real-time view of what's being transcribed:
```bash
venv/bin/python talk_spotter.py --live
```

Text appears as it's recognized, updating in place until each phrase is finalized.

### Debug audio

Save received audio to a WAV file:
```bash
venv/bin/python talk_spotter.py --save-wav debug.wav
```

Test transcription with a pre-recorded file:
```bash
venv/bin/python talk_spotter.py --test-file recording.wav
```

### All options

```
usage: talk_spotter.py [-h] [--config CONFIG] [--radio {kiwisdr,rtl_sdr}]
                       [--debug] [--save-wav FILE] [--test-file FILE]
                       [--spot-mode] [--no-post] [--live]
                       [--sota-login] [--sota-logout] [--sota-status]

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
  --live                Live transcription mode - clean real-time display
  --sota-login          Login to SOTA (one-time setup for spot posting)
  --sota-logout         Logout from SOTA (clear stored tokens)
  --sota-status         Check SOTA authentication status
```

## Standalone scripts

These scripts can be used independently for testing specific functionality:

- `kiwi_stream.py` - Stream and transcribe from a KiwiSDR
- `rtl_stream.py` - Stream and transcribe from an RTL-SDR
- `dx_cluster.py` - Test DX Cluster connectivity
- `pota_spotter.py` - Test POTA spot posting
- `sota_spotter.py` - SOTA authentication and spot posting

## Running at Startup

To run Talk Spotter automatically on boot (useful for a dedicated Pi), create a systemd service:

1. **Create the service file**
   ```bash
   sudo nano /etc/systemd/system/talkspotter.service
   ```

2. **Paste this configuration** (adjust paths and user as needed):
   ```ini
   [Unit]
   Description=Talk Spotter - Voice-activated radio spotting
   After=network.target

   [Service]
   Type=simple
   User=pi
   WorkingDirectory=/home/pi/talk-spotter
   ExecStart=/home/pi/talk-spotter/venv/bin/python talk_spotter.py --spot-mode
   Restart=on-failure
   RestartSec=10

   [Install]
   WantedBy=multi-user.target
   ```

3. **Enable and start the service**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable talkspotter
   sudo systemctl start talkspotter
   ```

4. **Useful commands**
   ```bash
   sudo systemctl status talkspotter   # Check status
   sudo journalctl -u talkspotter -f   # View live logs
   sudo systemctl restart talkspotter  # Restart after config changes
   ```

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

### Module Not Found Error

If you see "ModuleNotFoundError: No module named 'vosk'" (or similar), you're not using the virtual environment's Python. Make sure to run with `venv/bin/python talk_spotter.py` as shown in the Usage section above.

## License

MIT

Copyright 2026 Evan Boyar

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the “Software”), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## QR code

█████████████████████████████████
██ ▄▄▄▄▄ █ ▄▄ █▀ ██▀ █▀█ ▄▄▄▄▄ ██
██ █   █ ██▄█▀▀ ▀▄ ▄ ▄▄█ █   █ ██
██ █▄▄▄█ █ ▀▀▄ ▄▀█▀ ▄███ █▄▄▄█ ██
██▄▄▄▄▄▄▄█ ▀▄█▄█▄▀▄█▄▀ █▄▄▄▄▄▄▄██
██   ▀▀ ▄█ ▄█▄ █▀ ▀▀█ ▀   ▄██  ██
██  ▀ ▀█▄  ▄ ▀ ▄█▄▀█▀▄▀▀▄▄  ▄█▄██
████▄  ▄▄█   ████▀▄▀▀▄ █  ███▀ ██
██▄▀ ▀██▄▀▄█▀▄█▄▀ █▄  ▀▄  ▄███▄██
███ ███ ▄▄▀▄ ▄ █▀▀ ██▀▄▄ ▀██▀▀ ██
██▄▄ ▄▀ ▄▄ ▀█▀ █▄▄ ▄ ▄▀█▀█ ▄██▄██
██▄▄█▄▄█▄▄▀▄███ ▄▀ █▀█ ▄▄▄  ▀▄▀██
██ ▄▄▄▄▄ █▀▀█▄█▀█▄██▄▀ █▄█ ██▀▄██
██ █   █ ███▄▄ ▄█  ▀▄   ▄▄  ▀▄▀██
██ █▄▄▄█ █ ▀▄▀ ▄ ▄ █▀█▀▄█▀ ▀█▄▄██
██▄▄▄▄▄▄▄█▄█▄██▄▄▄████▄███▄▄██▄██
█████████████████████████████████
