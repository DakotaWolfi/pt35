#!/usr/bin/env python3
"""Opt-in NFC-B ISO14443-4 ATTRIB diagnostic for the recovered PT35 reader.

One shot only. Sends REQB (using the known-working NFC-B scanner), followed
by ATTRIB to the SAME PUPI. Does not send application APDUs, authenticate,
read protected memory, or change any card's persistent state.
The RF field is shut off before returning.
"""
import argparse
import sys
from pathlib import Path


def recovered_imports():
    # Always choose the original recovered Pi4 NFC driver. The simplified
    # migration driver has the same module name but incompatible symbols.
    folder = Path.home() / "pt35-old-recovery/pt35-nfc-bench/nfc"
    if not (folder / "nfc_poll.py").is_file():
        raise RuntimeError("Recovered Pi4 NFC source directory missing: " + str(folder))
    sys.path.insert(0, str(folder))
    from nfc_poll import configure, poll_b
    from nfc_config import reader_lock
    from nfcv_dump import Reader
    from nfcv_scan import FrameError, crc15693
    if not Path(sys.modules["nfcv_scan"].__file__).resolve().is_relative_to(folder.resolve()):
        raise RuntimeError("Refusing to use non-recovered NFC driver")
    return configure, poll_b, reader_lock, Reader, FrameError, crc15693


def attrib_command(pupi):
    """Conservative 106 kbps, 64-byte reader frame, ISO-DEP, CID=0."""
    if not isinstance(pupi, (bytes, bytearray)) or len(pupi) != 4:
        raise ValueError("ATTRIB requires the four PUPI bytes from ATQB")
    # ATTRIB | PUPI | Param1=00 (TR0/TR1 defaults, no EOF suppression)
    # Param2=05 (FSdI 5 = max 64-byte PCD frame)
    # Param3=01 (ISO-DEP protocol type)
    # Param4=00 (no CID)
    return bytes((0x1D,)) + bytes(pupi) + bytes((0x00, 0x05, 0x01, 0x00))


def parse_attrib_reply(data):
    """Return reported ISO-DEP activation values from a CRC-checked reply."""
    if len(data) < 1:
        raise ValueError("Empty ATTRIB response")
    # First reply byte: upper nibble MBLI, lower nibble CID.
    return {"mbli": data[0] >> 4, "cid": data[0] & 0x0F,
            "higher_layer_response": data[1:].hex().upper()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bus", type=int, default=1)
    args = parser.parse_args()
    configure, poll_b, reader_lock, Reader, FrameError, crc_b = recovered_imports()
    from smbus2 import SMBus

    print("PT35 NFC-B ISO-DEP activation probe (read-only)", flush=True)
    print("Close the NFC GUI; hold one NFC-B card over the antenna.", flush=True)
    print("No application commands will be sent.", flush=True)
    with reader_lock(f"i2c-{args.bus}"), SMBus(args.bus) as bus:
        reader = Reader(bus)
        try:
            reader.initialize(configure=lambda chip: configure(chip, "NFC-B"))
            try:
                found = poll_b(reader)
            except (FrameError, TimeoutError) as exc:
                print("No valid NFC-B ATQB:", exc, flush=True)
                return 2
            pupi_text, info = found
            atqb = bytes.fromhex(info["atqb"])
            print("Protocol: ISO/IEC 14443-B")
            print("PUPI:", pupi_text)
            print("ATQB application data:", atqb[5:9].hex().upper())
            print("ATQB protocol info:", atqb[9:12].hex().upper())
            frame = attrib_command(bytes.fromhex(pupi_text))
            print("ATTRIB request (without CRC):", frame.hex().upper(), flush=True)
            try:
                # Transmit with CRC, and validate the received CRC-B exactly
                # as the already-working REQB/ATQB path does.
                raw, fifo, errors = reader.transceive(
                    frame, 0.20, tx_command=0xC4, check_errors=True, max_rx=64
                )
                if fifo & 0x0F:
                    raise FrameError("framing", "Partial byte in ATTRIB reply")
                if len(raw) < 3 or crc_b(raw[:-2]) != int.from_bytes(raw[-2:], "little"):
                    raise FrameError("crc", "Invalid ATTRIB response CRC-B")
                reply = raw[:-2]
                result = parse_attrib_reply(reply)
            except (FrameError, TimeoutError) as exc:
                print("ATTRIB not completed:", exc)
                print("Discovery was successful; ISO-DEP activation needs investigation.")
                return 3
            print("ISO-DEP activation: CONFIRMED")
            print("ATTRIB response:", reply.hex().upper())
            print("MBLI:", result["mbli"], "CID:", result["cid"])
            if result["higher_layer_response"]:
                print("Higher-layer response:", result["higher_layer_response"])
            else:
                print("Higher-layer response: none")
            print("No APDU or memory-read operation was attempted.")
            return 0
        finally:
            # Normal shutdown path: remove RF field even on a failed exchange.
            try:
                reader.shutdown()
            except OSError as exc:
                print("Warning: RF shutdown failed:", exc, file=sys.stderr)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, ImportError) as exc:
        print("Probe error:", exc, file=sys.stderr)
        sys.exit(1)
