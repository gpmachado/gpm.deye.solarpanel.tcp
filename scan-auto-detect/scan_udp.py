#!/usr/bin/env python3
"""
Quick UDP scan for Solarman loggers on the local network.

Usage:
    python3 scan_udp.py

No dependencies — works with Python 3 out of the box.
Sends both known discovery payloads and listens for 5 seconds.
Prints IP, MAC and serial number of any logger that responds.
"""

import socket
import time

DISCOVERY_PORT = 48899
PAYLOADS = [b"WIFIKIT-214028-READ", b"HF-A11ASSISTHREAD"]
TIMEOUT = 5.0

def scan() -> None:
    found: dict[str, str] = {}  # ip -> raw reply

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(0.5)

    try:
        sock.bind(("", DISCOVERY_PORT))
    except OSError:
        sock.bind(("", 0))  # fallback to random port

    print(f"Scanning for Solarman loggers on UDP port {DISCOVERY_PORT}...")
    print(f"Waiting {TIMEOUT}s for replies...\n")

    deadline = time.time() + TIMEOUT
    sent = False

    while time.time() < deadline:
        if not sent:
            for payload in PAYLOADS:
                try:
                    sock.sendto(payload, ("255.255.255.255", DISCOVERY_PORT))
                except Exception as e:
                    print(f"  [warn] broadcast failed: {e}")
            sent = True

        try:
            data, addr = sock.recvfrom(1024)
            ip = addr[0]
            if ip not in found:
                found[ip] = data.decode("utf-8", errors="replace").strip()
        except socket.timeout:
            pass
        except Exception:
            pass

    sock.close()

    if not found:
        print("No loggers found.")
        print()
        print("Possible reasons:")
        print("  - Logger and computer are on different network segments or VLANs")
        print("  - Router is blocking UDP broadcast between devices")
        print("  - Logger is in AP mode (connect to its Wi-Fi first)")
        print("  - Try entering the IP and serial manually in the Homey app")
        return

    print(f"Found {len(found)} logger(s):\n")
    for ip, reply in found.items():
        # Typical reply format: "IP,MAC,Serial"  e.g. "192.168.1.100,AA:BB:CC:11:22:33,2304123456"
        parts = [p.strip() for p in reply.split(",")]
        mac    = parts[1] if len(parts) > 1 else "—"
        serial = parts[2] if len(parts) > 2 else "—"
        print(f"  IP     : {ip}")
        print(f"  MAC    : {mac}")
        print(f"  Serial : {serial}")
        print(f"  Raw    : {reply}")
        print()

    print("Use the IP and Serial above when pairing manually in the Homey app.")

if __name__ == "__main__":
    scan()
