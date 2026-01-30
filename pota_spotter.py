#!/usr/bin/env python3
"""
POTA (Parks on the Air) spot posting client.

Posts spots to the POTA API at https://api.pota.app/spot
"""

import argparse
import logging
import requests
from typing import Optional


class POTASpotter:
    """Client for posting spots to POTA."""

    API_URL = "https://api.pota.app/spot"
    USER_AGENT = "TalkSpotter/1.0 (https://github.com/EvanBoyar/talk-spotter)"

    def __init__(self, spotter_callsign: str):
        """
        Initialize POTA spotter.

        Args:
            spotter_callsign: Callsign of the person posting the spot
        """
        self.spotter_callsign = spotter_callsign.upper()

    def post_spot(
        self,
        activator: str,
        frequency_khz: float,
        park_ref: str,
        mode: str = "SSB",
        comments: str = ""
    ) -> dict:
        """
        Post a spot to POTA.

        Args:
            activator: Callsign of the activator being spotted
            frequency_khz: Frequency in kHz (e.g., 14250)
            park_ref: POTA park reference (e.g., "K-1234")
            mode: Operating mode (default: SSB)
            comments: Optional comments

        Returns:
            dict with 'success' (bool) and 'message' or 'error' keys

        Raises:
            requests.RequestException: On network errors
        """
        # Build the spot payload
        payload = {
            "activator": activator.upper(),
            "spotter": self.spotter_callsign,
            "frequency": str(frequency_khz),
            "reference": park_ref.upper(),
            "mode": mode.upper(),
            "source": "TalkSpotter",
            "comments": comments or "Spotted via TalkSpotter"
        }

        headers = {
            "Content-Type": "application/json",
            "User-Agent": self.USER_AGENT
        }

        logging.debug(f"POTA spot payload: {payload}")

        try:
            response = requests.post(
                self.API_URL,
                json=payload,
                headers=headers,
                timeout=10
            )

            logging.debug(f"POTA API response: {response.status_code} {response.text}")

            if response.status_code == 200:
                return {"success": True, "message": "Spot posted successfully"}
            else:
                # Try to extract error message from response
                try:
                    error_data = response.json()
                    error_msg = error_data.get("message", response.text)
                except:
                    error_msg = response.text or f"HTTP {response.status_code}"

                return {"success": False, "error": error_msg}

        except requests.Timeout:
            return {"success": False, "error": "Request timed out"}
        except requests.RequestException as e:
            return {"success": False, "error": str(e)}


def post_spot(
    activator: str,
    frequency_khz: float,
    park_ref: str,
    spotter_callsign: str,
    mode: str = "SSB",
    comments: str = ""
) -> bool:
    """
    Convenience function to post a POTA spot.

    Args:
        activator: Callsign of the activator
        frequency_khz: Frequency in kHz
        park_ref: POTA park reference (e.g., "K-1234")
        spotter_callsign: Your callsign
        mode: Operating mode (default: SSB)
        comments: Optional comments

    Returns:
        True if spot was posted successfully, False otherwise
    """
    spotter = POTASpotter(spotter_callsign)
    result = spotter.post_spot(activator, frequency_khz, park_ref, mode, comments)

    if result["success"]:
        logging.info(f"POTA spot posted: {activator} at {park_ref} on {frequency_khz} kHz")
        return True
    else:
        logging.error(f"POTA spot failed: {result.get('error', 'Unknown error')}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Post a spot to POTA")
    parser.add_argument("--activator", "-a", required=True, help="Activator callsign")
    parser.add_argument("--spotter", "-s", required=True, help="Your callsign (spotter)")
    parser.add_argument("--freq", "-f", type=float, required=True, help="Frequency in kHz")
    parser.add_argument("--park", "-p", required=True, help="Park reference (e.g., K-1234)")
    parser.add_argument("--mode", "-m", default="SSB", help="Mode (default: SSB)")
    parser.add_argument("--comment", "-c", default="", help="Comment")
    parser.add_argument("--debug", "-d", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format='%(asctime)s %(levelname)s: %(message)s'
    )

    print(f"Posting POTA spot: {args.activator} at {args.park} on {args.freq} kHz ({args.mode})")
    print(f"Spotter: {args.spotter}")

    spotter = POTASpotter(args.spotter)
    result = spotter.post_spot(
        activator=args.activator,
        frequency_khz=args.freq,
        park_ref=args.park,
        mode=args.mode,
        comments=args.comment
    )

    if result["success"]:
        print(f"Success: {result['message']}")
        return 0
    else:
        print(f"Failed: {result['error']}")
        return 1


if __name__ == "__main__":
    exit(main())
