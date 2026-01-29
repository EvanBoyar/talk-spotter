#!/usr/bin/env python3
"""
DX Cluster client for posting spots via telnet.
"""

import argparse
import socket
import time


class DXCluster:
    """Simple DX Cluster telnet client."""

    def __init__(self, host: str, port: int, callsign: str, timeout: float = 10.0):
        self.host = host
        self.port = port
        self.callsign = callsign.upper()
        self.timeout = timeout
        self.sock = None

    def connect(self) -> str:
        """Connect to the DX cluster and log in. Returns welcome message."""
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect((self.host, self.port))

        # Read welcome/login prompt
        response = self._read_until_prompt()

        # Send callsign to log in
        self._send(self.callsign)
        login_response = self._read_until_prompt()

        return response + login_response

    def spot(self, frequency: float, dx_callsign: str, comment: str = "") -> str:
        """
        Post a DX spot.

        Args:
            frequency: Frequency in kHz (e.g., 14230)
            dx_callsign: Callsign of the station being spotted
            comment: Optional comment/remarks

        Returns:
            Server response
        """
        if not self.sock:
            raise RuntimeError("Not connected. Call connect() first.")

        # Build DX command
        cmd = f"DX {frequency:.1f} {dx_callsign.upper()}"
        if comment:
            cmd += f" {comment}"

        self._send(cmd)
        return self._read_until_prompt()

    def disconnect(self):
        """Disconnect from the cluster."""
        if self.sock:
            try:
                self._send("BYE")
                self.sock.close()
            except:
                pass
            self.sock = None

    def _send(self, data: str):
        """Send a line to the server."""
        self.sock.sendall((data + "\r\n").encode('ascii', errors='ignore'))

    def _read_until_prompt(self, timeout: float = None) -> str:
        """Read data until we get a prompt or timeout."""
        if timeout is None:
            timeout = self.timeout

        self.sock.settimeout(timeout)
        data = b""
        end_time = time.time() + timeout

        while time.time() < end_time:
            try:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                data += chunk
                # Check for common prompt patterns
                text = data.decode('ascii', errors='ignore')
                if text.rstrip().endswith('>') or text.rstrip().endswith(':'):
                    # Give a moment for any additional data
                    self.sock.settimeout(0.5)
                    try:
                        extra = self.sock.recv(4096)
                        data += extra
                    except socket.timeout:
                        pass
                    break
            except socket.timeout:
                break

        return data.decode('ascii', errors='ignore')

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()


def main():
    parser = argparse.ArgumentParser(description="Post a spot to a DX Cluster")
    parser.add_argument("--host", "-s", default="dx.w1nr.net", help="DX Cluster host")
    parser.add_argument("--port", "-p", type=int, default=7300, help="DX Cluster port")
    parser.add_argument("--call", "-c", required=True, help="Your callsign")
    parser.add_argument("--freq", "-f", type=float, help="Frequency in kHz")
    parser.add_argument("--dx", "-d", help="DX callsign to spot")
    parser.add_argument("--comment", "-m", default="", help="Spot comment")
    parser.add_argument("--test", action="store_true", help="Test connection only (no spot)")

    args = parser.parse_args()

    print(f"Connecting to {args.host}:{args.port} as {args.call}...")

    try:
        with DXCluster(args.host, args.port, args.call) as cluster:
            print("Connected!")

            if args.test:
                print("Test mode - disconnecting without posting spot")
            elif args.freq and args.dx:
                print(f"Posting spot: {args.dx} on {args.freq} kHz")
                response = cluster.spot(args.freq, args.dx, args.comment)
                print(f"Response: {response}")
            else:
                print("No spot to post (use --freq and --dx to post a spot)")

    except socket.timeout:
        print("Error: Connection timed out")
        return 1
    except socket.error as e:
        print(f"Error: {e}")
        return 1

    print("Done.")
    return 0


if __name__ == "__main__":
    exit(main())
