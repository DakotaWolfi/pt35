#!/usr/bin/env python3
"""
Standalone iLEDColor / iLEDEyes panel probe for Linux (PT35).

No CollarPet imports. Uses Bleak directly.

Examples:
  python3 iledcolor_standalone.py --scan 10
  python3 iledcolor_standalone.py --scan 10 --all
  python3 iledcolor_standalone.py --test AA:BB:CC:DD:EE:FF
  python3 iledcolor_standalone.py --test AA:BB:CC:DD:EE:FF --width 48 --height 12 --color-type 3
"""

import argparse
import asyncio
import struct
import sys
import zlib

try:
    from bleak import BleakScanner, BleakClient
except ImportError:
    print("Missing dependency: bleak")
    print("Install it with:  python3 -m pip install --user bleak")
    raise SystemExit(2)

SERVICE = "0000a950-0000-1000-8000-00805f9b34fb"
WRITE_CONTROL = "0000a951-0000-1000-8000-00805f9b34fb"
WRITE_BULK = "0000a952-0000-1000-8000-00805f9b34fb"
NOTIFY = "0000a953-0000-1000-8000-00805f9b34fb"

CMD_FRAGMENT = 0x00
CMD_COMPLETE = 0x01
CMD_TEMP_PROGRAM = 0x06
CMD_BRIGHTNESS = 0x09
CMD_SCREEN = 0x0A

COMPANY_CODE = 0x5442


def build_frame(cmd: int, data: bytes) -> bytes:
    dl = len(data) + 2
    body = bytes([0x54, cmd, (dl >> 8) & 0xFF, dl & 0xFF]) + data
    ck = sum(body) & 0xFFFF
    return body + bytes([(ck >> 8) & 0xFF, ck & 0xFF])


def crc32c(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ (0x82F63B78 if (crc & 1) else 0)
    return crc ^ 0xFFFFFFFF


def pack_partition(x, y, w, h, ptype, total_frames, effect=0, speed=50,
                   residence=5, border=0, luminance=35, frame_data=b""):
    hdr = struct.pack(">HHHH", x, y, w, h)
    hdr += b"\x00\x00\x00"
    hdr += bytes([ptype])
    hdr += struct.pack(">H", total_frames)
    hdr += bytes([effect, speed, residence, border, luminance])
    hdr += b"\x00\x00\x00"
    return hdr + frame_data


def pack_program(partitions):
    starts = []
    off = 0
    for p in partitions:
        starts.append(off)
        off += len(p)
    while len(starts) < 4:
        starts.append(0)
    content = b"".join(partitions)
    pid = crc32c(content)
    pkg = struct.pack(">I", pid)
    pkg += bytes([len(partitions)]) + b"\x00\x00\x00"
    for s in starts[:4]:
        pkg += struct.pack(">I", s)
    pkg += content
    return pkg, pid


def parse_panel_advertisement(company_id, data):
    # Bleak splits the first two manufacturer bytes out as a little-endian company_id.
    full = bytes([company_id & 0xFF, (company_id >> 8) & 0xFF]) + bytes(data)
    if len(full) < 17:
        return None
    u16 = lambda at: (full[at] << 8) | full[at + 1]
    if u16(1) != COMPANY_CODE:
        return None
    return {
        "category": full[0],
        "company_code": u16(1),
        "app_code": u16(3),
        "height": u16(5),
        "width": u16(7),
        "color_type": full[9],
        "rotation": full[10],
        "firmware": u16(11),
        "client_id": u16(13),
        "function_bits": u16(15),
    }


def color_name(t):
    return {
        0: "mono",
        1: "mono",
        2: "rainbow",
        3: "RGB888",
        4: "RGB565",
        5: "RGB332",
    }.get(t, f"unknown({t})")


def make_test_pixels(w, h, color_type):
    colors = [
        (255, 0, 0), (255, 128, 0), (0, 255, 0), (0, 255, 255),
        (0, 0, 255), (255, 0, 255), (255, 255, 255), (0, 0, 0)
    ]
    out = bytearray()
    for y in range(h):
        for x in range(w):
            r, g, b = colors[min(7, x * 8 // max(1, w))]
            # Orientation markers in the corners.
            if x == 0 and y == 0:
                r, g, b = 255, 255, 255
            elif x == w - 1 and y == 0:
                r, g, b = 255, 0, 0
            elif x == 0 and y == h - 1:
                r, g, b = 0, 255, 0
            elif x == w - 1 and y == h - 1:
                r, g, b = 0, 0, 255

            if color_type == 3:  # RGB888
                out += bytes((r, g, b))
            elif color_type == 4:  # RGB565, vendor packing
                out += bytes(((r & 0xF8) | (g >> 5), ((g & 0x1C) << 3) | (b >> 3)))
            elif color_type == 5:  # RGB332
                out += bytes(((r & 0xE0) | ((g & 0xE0) >> 3) | ((b & 0xC0) >> 6),))
            else:
                raise ValueError("Test upload currently supports RGB888/RGB565/RGB332 only")
    return bytes(out)


def parse_notification(raw: bytes):
    raw = bytes(raw)
    if len(raw) < 6 or raw[0] != 0x54:
        return ("bad", raw)
    cmd = raw[1]
    dl = (raw[2] << 8) | raw[3]

    if cmd == CMD_FRAGMENT and dl == 5 and len(raw) == 11:
        wrap = int.from_bytes(raw[4:8], "big")
        status = raw[8]
        return ("fragment", wrap, status)

    if dl < 2 or len(raw) != 4 + dl:
        return ("bad", raw)

    data = raw[4:4 + dl - 2]
    return ("ack", cmd, bytes(data))


async def scan(seconds, show_all=False):
    print(f"Scanning for {seconds:.1f}s ...")
    found = {}

    def callback(device, adv):
        name = adv.local_name or device.name or "(no name)"
        matched = False

        for company_id, data in adv.manufacturer_data.items():
            info = parse_panel_advertisement(company_id, data)
            if info:
                matched = True
                found[device.address] = (device, adv, info)
                print(
                    f"[PANEL] {device.address}  {name}  "
                    f"{info['width']}x{info['height']} {color_name(info['color_type'])}  "
                    f"rot={info['rotation'] * 90}° fw=0x{info['firmware']:04X} "
                    f"app=0x{info['app_code']:04X}"
                )

        if show_all and not matched:
            print(f"[BLE]   {device.address}  {name}  RSSI={getattr(adv, 'rssi', '?')}")

    scanner = BleakScanner(callback)
    await scanner.start()
    await asyncio.sleep(seconds)
    await scanner.stop()

    if not found:
        print("\nNo matching iLEDColor-family manufacturer packet was decoded.")
        print("Try again with --all to see every BLE device and its name.")
    else:
        print(f"\nFound {len(found)} matching panel(s).")
    return found


async def wait_for(q, timeout=3.0):
    return await asyncio.wait_for(q.get(), timeout)


async def upload_test(address, width, height, color_type, chunk_size, luminance):
    print(f"Connecting to {address} ...")
    q = asyncio.Queue()

    def on_notify(_sender, data):
        parsed = parse_notification(data)
        print("RX:", bytes(data).hex(" "), "->", parsed)
        q.put_nowait(parsed)

    async with BleakClient(address, timeout=15.0) as client:
        print("Connected.")
        print("Services:")
        for s in client.services:
            print(" ", s.uuid)

        await client.start_notify(NOTIFY, on_notify)
        await asyncio.sleep(0.2)

        # These writes are intentionally conservative and reversible.
        print(f"Setting display brightness to {luminance}% and screen ON ...")
        await client.write_gatt_char(WRITE_CONTROL, build_frame(CMD_BRIGHTNESS, bytes([luminance])), response=False)
        await asyncio.sleep(0.1)
        await client.write_gatt_char(WRITE_CONTROL, build_frame(CMD_SCREEN, b"\x01"), response=False)
        await asyncio.sleep(0.1)

        pixels = make_test_pixels(width, height, color_type)
        part = pack_partition(
            0, 0, width, height,
            ptype=1, total_frames=1,
            effect=0, speed=50, residence=5,
            border=0, luminance=luminance,
            frame_data=pixels
        )
        program, pid = pack_program([part])

        print(f"Program bytes: {len(program)}, programId=0x{pid:08X}")
        announce = struct.pack(">II", pid, len(program)) + b"\x00\x00\x00"
        await client.write_gatt_char(WRITE_CONTROL, build_frame(CMD_TEMP_PROGRAM, announce), response=False)

        while True:
            n = await wait_for(q)
            if n[0] == "ack" and n[1] == CMD_TEMP_PROGRAM:
                status = n[2][0] if n[2] else 0xFF
                print("Announce status:", status)
                if status == 3:
                    print("Program already cached. Nothing else to upload.")
                    return
                if status != 1:
                    raise RuntimeError(f"Panel rejected announce with status {status}")
                break

        offset = 0
        wrap = 0
        while offset < len(program):
            chunk = program[offset:offset + chunk_size]
            payload = wrap.to_bytes(4, "big") + len(chunk).to_bytes(2, "big") + chunk
            await client.write_gatt_char(WRITE_BULK, build_frame(CMD_FRAGMENT, payload), response=False)

            while True:
                n = await wait_for(q)
                if n[0] == "fragment" and n[1] == wrap:
                    if n[2] != 1:
                        raise RuntimeError(f"Fragment {wrap} rejected with status {n[2]}")
                    break

            offset += len(chunk)
            wrap += 1
            print(f"Uploaded {offset}/{len(program)} bytes")

        await client.write_gatt_char(WRITE_BULK, build_frame(CMD_COMPLETE, b"\x01"), response=False)

        while True:
            n = await wait_for(q)
            if n[0] == "ack" and n[1] == CMD_COMPLETE:
                ok = bool(n[2] and n[2][0] == 1)
                print("Complete:", "OK" if ok else f"FAILED {n}")
                if not ok:
                    raise RuntimeError("Panel did not accept completion")
                break

        print("\nTest upload completed. Look at the collar.")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", type=float, metavar="SECONDS", help="scan only; makes no writes")
    ap.add_argument("--all", action="store_true", help="during scan, show every BLE device")
    ap.add_argument("--test", metavar="ADDRESS", help="connect and upload a low-brightness test pattern")
    ap.add_argument("--width", type=int, default=48)
    ap.add_argument("--height", type=int, default=12)
    ap.add_argument("--color-type", type=int, default=3, choices=(3, 4, 5))
    ap.add_argument("--chunk", type=int, default=180, help="bulk data bytes per fragment (default 180)")
    ap.add_argument("--brightness", type=int, default=25, help="test brightness 1..100 (default 25)")
    args = ap.parse_args()

    if not args.scan and not args.test:
        ap.error("use --scan SECONDS or --test ADDRESS")

    if args.scan:
        await scan(args.scan, args.all)

    if args.test:
        if not (1 <= args.brightness <= 100):
            ap.error("--brightness must be 1..100")
        if not (1 <= args.chunk <= 492):
            ap.error("--chunk must be 1..492")
        await upload_test(args.test, args.width, args.height, args.color_type, args.chunk, args.brightness)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
