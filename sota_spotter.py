#!/usr/bin/env python3
"""
SOTA (Summits on the Air) spot posting client.

Posts spots to the SOTA API at https://api-db2.sota.org.uk/api/spots
Uses OAuth 2.0 Device Code flow for authentication.
"""

import argparse
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import requests


class SOTAAuth:
    """OAuth 2.0 authentication for SOTA using Device Code flow."""

    SSO_BASE = "https://sso.sota.org.uk/auth/realms/SOTA/protocol/openid-connect"
    DEVICE_ENDPOINT = f"{SSO_BASE}/auth/device"
    TOKEN_ENDPOINT = f"{SSO_BASE}/token"

    # PoLo's client ID - SOTA doesn't require client registration
    CLIENT_ID = "polo"

    def __init__(self, token_file: Optional[str] = None):
        """
        Initialize SOTA authentication.

        Args:
            token_file: Path to store tokens. Defaults to ~/.config/talkspotter/sota_tokens.json
        """
        if token_file:
            self.token_file = Path(token_file)
        else:
            config_dir = Path.home() / ".config" / "talkspotter"
            config_dir.mkdir(parents=True, exist_ok=True)
            self.token_file = config_dir / "sota_tokens.json"

        self._tokens = self._load_tokens()

    def _load_tokens(self) -> dict:
        """Load tokens from file."""
        if self.token_file.exists():
            try:
                with open(self.token_file) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logging.warning(f"Could not load SOTA tokens: {e}")
        return {}

    def _save_tokens(self):
        """Save tokens to file."""
        try:
            with open(self.token_file, "w") as f:
                json.dump(self._tokens, f, indent=2)
            # Restrict permissions to owner only
            os.chmod(self.token_file, 0o600)
        except IOError as e:
            logging.error(f"Could not save SOTA tokens: {e}")

    @property
    def is_authenticated(self) -> bool:
        """Check if we have tokens (may still need refresh)."""
        return bool(self._tokens.get("refresh_token"))

    @property
    def access_token(self) -> Optional[str]:
        """Get current access token."""
        return self._tokens.get("access_token")

    @property
    def id_token(self) -> Optional[str]:
        """Get current ID token."""
        return self._tokens.get("id_token")

    def device_login(self) -> bool:
        """
        Perform device code login flow.

        Returns:
            True if login successful, False otherwise
        """
        print("Starting SOTA device login...")

        # Request device code
        try:
            response = requests.post(
                self.DEVICE_ENDPOINT,
                data={"client_id": self.CLIENT_ID},
                timeout=10
            )
            response.raise_for_status()
            try:
                device_data = response.json()
            except ValueError:
                print("Failed to parse device code response (invalid JSON).")
                return False
        except requests.RequestException as e:
            print(f"Failed to get device code: {e}")
            return False

        # Show user instructions
        user_code = device_data.get("user_code")
        verification_uri = device_data.get("verification_uri_complete") or device_data.get("verification_uri")
        expires_in = device_data.get("expires_in", 600)
        interval = device_data.get("interval", 5)
        device_code = device_data.get("device_code")

        print("\n" + "=" * 50)
        print("SOTA Login Required")
        print("=" * 50)
        print(f"\n1. Go to: {verification_uri}")
        if user_code:
            print(f"2. Enter code: {user_code}")
        print(f"\nWaiting for you to complete login (expires in {expires_in // 60} minutes)...")
        print("Press Ctrl+C to cancel.\n")

        # Poll for token
        start_time = time.time()
        while time.time() - start_time < expires_in:
            time.sleep(interval)

            try:
                response = requests.post(
                    self.TOKEN_ENDPOINT,
                    data={
                        "client_id": self.CLIENT_ID,
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        "device_code": device_code
                    },
                    timeout=10
                )

                if response.status_code == 200:
                    # Success!
                    token_data = response.json()
                    self._tokens = {
                        "access_token": token_data.get("access_token"),
                        "refresh_token": token_data.get("refresh_token"),
                        "id_token": token_data.get("id_token"),
                        "expires_at": time.time() + token_data.get("expires_in", 300)
                    }
                    self._save_tokens()
                    print("\nLogin successful! Tokens saved.")
                    return True

                # Check for pending/slow_down responses
                try:
                    error_data = response.json()
                    error = error_data.get("error")
                except ValueError:
                    print(f"\nUnexpected response from SOTA auth service: {response.text}")
                    return False

                if error == "authorization_pending":
                    # User hasn't completed login yet
                    print(".", end="", flush=True)
                    continue
                elif error == "slow_down":
                    # Increase polling interval
                    interval += 5
                    continue
                elif error == "expired_token":
                    print("\nDevice code expired. Please try again.")
                    return False
                elif error == "access_denied":
                    print("\nLogin was denied.")
                    return False
                else:
                    print(f"\nUnexpected error: {error}")
                    return False

            except requests.RequestException as e:
                logging.debug(f"Polling error (will retry): {e}")
                continue

        print("\nLogin timed out. Please try again.")
        return False

    def refresh_tokens(self) -> bool:
        """
        Refresh access token using refresh token.

        Returns:
            True if refresh successful, False otherwise
        """
        refresh_token = self._tokens.get("refresh_token")
        if not refresh_token:
            logging.debug("No refresh token available")
            return False

        try:
            response = requests.post(
                self.TOKEN_ENDPOINT,
                data={
                    "client_id": self.CLIENT_ID,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token
                },
                timeout=10
            )

            if response.status_code == 200:
                token_data = response.json()
                self._tokens.update({
                    "access_token": token_data.get("access_token"),
                    "id_token": token_data.get("id_token"),
                    "expires_at": time.time() + token_data.get("expires_in", 300)
                })
                # Update refresh token if a new one was issued
                if token_data.get("refresh_token"):
                    self._tokens["refresh_token"] = token_data["refresh_token"]
                self._save_tokens()
                logging.debug("SOTA tokens refreshed successfully")
                return True
            else:
                try:
                    error_data = response.json()
                    error = error_data.get("error")
                except ValueError:
                    logging.warning(
                        "Unexpected response from SOTA auth service while refreshing tokens"
                    )
                    return False
                if error == "invalid_grant":
                    # Refresh token expired - user needs to re-login
                    logging.warning("SOTA refresh token expired - please run --sota-login")
                    self._tokens = {}
                    self._save_tokens()
                return False

        except requests.RequestException as e:
            logging.error(f"Failed to refresh SOTA tokens: {e}")
            return False

    def ensure_valid_token(self) -> bool:
        """
        Ensure we have a valid access token, refreshing if needed.

        Returns:
            True if we have a valid token, False otherwise
        """
        if not self.is_authenticated:
            return False

        # Check if token is expired or about to expire (within 60 seconds)
        expires_at = self._tokens.get("expires_at", 0)
        if time.time() > expires_at - 60:
            logging.debug("SOTA access token expired, refreshing...")
            return self.refresh_tokens()

        return True

    def logout(self):
        """Clear stored tokens."""
        self._tokens = {}
        if self.token_file.exists():
            self.token_file.unlink()
        print("SOTA logout complete.")


class SOTASpotter:
    """Client for posting spots to SOTA."""

    API_URL = "https://api-db2.sota.org.uk/api/spots"
    USER_AGENT = "TalkSpotter/1.0 (https://github.com/EvanBoyar/talk-spotter)"

    def __init__(self, spotter_callsign: str, auth: Optional[SOTAAuth] = None):
        """
        Initialize SOTA spotter.

        Args:
            spotter_callsign: Callsign of the person posting the spot
            auth: SOTAAuth instance (creates one if not provided)
        """
        self.spotter_callsign = spotter_callsign.upper()
        self.auth = auth or SOTAAuth()

    def post_spot(
        self,
        activator: str,
        frequency_khz: float,
        summit_ref: str,
        mode: str = "SSB",
        comments: str = ""
    ) -> dict:
        """
        Post a spot to SOTA.

        Args:
            activator: Callsign of the activator being spotted
            frequency_khz: Frequency in kHz (e.g., 14285)
            summit_ref: SOTA summit reference (e.g., "W4C/CM-001")
            mode: Operating mode (default: SSB)
            comments: Optional comments

        Returns:
            dict with 'success' (bool) and 'message' or 'error' keys
        """
        # Ensure we have valid tokens
        if not self.auth.ensure_valid_token():
            return {
                "success": False,
                "error": "Not authenticated. Run with --sota-login first."
            }

        # Parse summit reference into association and code
        # Format: "W4C/CM-001" -> association="W4C", summitCode="CM-001"
        parts = summit_ref.upper().split("/", 1)
        if len(parts) != 2:
            return {
                "success": False,
                "error": f"Invalid summit reference format: {summit_ref} (expected format: W4C/CM-001)"
            }

        association_code = parts[0]
        summit_code = parts[1]

        # Convert frequency to MHz string (SOTA API expects MHz)
        frequency_mhz = f"{frequency_khz / 1000:.4f}"

        # Build the spot payload
        payload = {
            "associationCode": association_code,
            "summitCode": summit_code,
            "activatorCallsign": activator.upper(),
            "frequency": frequency_mhz,
            "mode": mode.upper(),
            "comments": comments or "Spotted via TalkSpotter",
            "type": "NORMAL",
            "id": 0  # Must be 0 for new spots
        }

        headers = {
            "Content-Type": "application/json",
            "User-Agent": self.USER_AGENT,
            "Authorization": f"bearer {self.auth.access_token}",
            "id_token": self.auth.id_token
        }

        logging.debug(f"SOTA spot payload: {payload}")

        try:
            response = requests.post(
                self.API_URL,
                json=payload,
                headers=headers,
                timeout=10
            )

            logging.debug(f"SOTA API response: {response.status_code} {response.text}")

            if response.status_code == 200:
                return {"success": True, "message": "Spot posted successfully"}
            elif response.status_code in (401, 403):
                # Try refreshing tokens and retry once
                if self.auth.refresh_tokens():
                    headers["Authorization"] = f"bearer {self.auth.access_token}"
                    headers["id_token"] = self.auth.id_token
                    response = requests.post(
                        self.API_URL,
                        json=payload,
                        headers=headers,
                        timeout=10
                    )
                    if response.status_code == 200:
                        return {"success": True, "message": "Spot posted successfully"}

                return {
                    "success": False,
                    "error": "Authentication failed. Try running --sota-login again."
                }
            else:
                try:
                    error_data = response.json()
                    error_msg = error_data.get("message", response.text)
                except Exception:
                    error_msg = response.text or f"HTTP {response.status_code}"

                return {"success": False, "error": error_msg}

        except requests.Timeout:
            return {"success": False, "error": "Request timed out"}
        except requests.RequestException as e:
            return {"success": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="SOTA spot posting tool")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Login command
    login_parser = subparsers.add_parser("login", help="Login to SOTA")

    # Logout command
    logout_parser = subparsers.add_parser("logout", help="Logout from SOTA")

    # Spot command
    spot_parser = subparsers.add_parser("spot", help="Post a spot to SOTA")
    spot_parser.add_argument("--activator", "-a", required=True, help="Activator callsign")
    spot_parser.add_argument("--spotter", "-s", required=True, help="Your callsign (spotter)")
    spot_parser.add_argument("--freq", "-f", type=float, required=True, help="Frequency in kHz")
    spot_parser.add_argument("--summit", "-S", required=True, help="Summit reference (e.g., W4C/CM-001)")
    spot_parser.add_argument("--mode", "-m", default="SSB", help="Mode (default: SSB)")
    spot_parser.add_argument("--comment", "-c", default="", help="Comment")

    # Status command
    status_parser = subparsers.add_parser("status", help="Check authentication status")

    parser.add_argument("--debug", "-d", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format='%(asctime)s %(levelname)s: %(message)s'
    )

    auth = SOTAAuth()

    if args.command == "login":
        auth.device_login()

    elif args.command == "logout":
        auth.logout()

    elif args.command == "status":
        if auth.is_authenticated:
            if auth.ensure_valid_token():
                print("SOTA: Authenticated (tokens valid)")
            else:
                print("SOTA: Tokens expired - run 'login' to re-authenticate")
        else:
            print("SOTA: Not authenticated - run 'login' to authenticate")

    elif args.command == "spot":
        if not auth.is_authenticated:
            print("Not logged in. Run 'login' first.")
            return 1

        print(f"Posting SOTA spot: {args.activator} at {args.summit} on {args.freq} kHz ({args.mode})")
        print(f"Spotter: {args.spotter}")

        spotter = SOTASpotter(args.spotter, auth)
        result = spotter.post_spot(
            activator=args.activator,
            frequency_khz=args.freq,
            summit_ref=args.summit,
            mode=args.mode,
            comments=args.comment
        )

        if result["success"]:
            print(f"Success: {result['message']}")
            return 0
        else:
            print(f"Failed: {result['error']}")
            return 1

    else:
        parser.print_help()
        return 0

    return 0


if __name__ == "__main__":
    exit(main())
