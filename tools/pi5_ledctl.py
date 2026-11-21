#!/usr/bin/env python3
"""Send a PT35 NeoPixel daemon command (pi5 and legacy command names)."""
import os
import socket
import sys
path=os.getenv("PT35_LED_SOCKET",f"/run/user/{os.getuid()}/pt35-led.sock")
if len(sys.argv)<2:
    raise SystemExit("Usage: pt35-ledctl off|idle|rainbow|battery|status|color R G B|flash R G B")
try:
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(4)
        sock.connect(path)
        sock.sendall((" ".join(sys.argv[1:])+"\n").encode())
        print(sock.recv(512).decode().strip())
except (OSError,TimeoutError) as exc:
    print(f"PT35 LED service unavailable: {exc}",file=sys.stderr)
    raise SystemExit(1)
