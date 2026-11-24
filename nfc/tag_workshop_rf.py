"""Experimental type-2 NFC tag I/O, isolated from the recovered reader GUI.

No command can modify UID, CC, static/dynamic lock, password or config pages.
Writes are restricted to CC-advertised Type 2 user memory and always
require pre-read, UID match, a saved backup, and per-page readback.
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RECOVERED = Path.home() / "pt35-old-recovery/pt35-nfc-bench/nfc"


def driver():
    # Recovered NFC drivers always first; the migration versions do not expose
    # the same API. Never import an unverified lookalike module.
    if not (RECOVERED / "nfc_poll.py").exists():
        raise RuntimeError("Recovered Pi4 NFC drivers missing")
    sys.path.insert(0, str(RECOVERED))
    from nfc_poll import configure, poll_a, crc_a, receive
    from nfcv_dump import Reader
    from nfc_config import reader_lock
    from nfcv_scan import FrameError
    if Path(sys.modules["nfc_poll"].__file__).resolve().parent != RECOVERED.resolve():
        raise RuntimeError("Wrong NFC driver loaded")
    return configure, poll_a, crc_a, receive, Reader, reader_lock, FrameError


def read_all(chip, poll_a, receive, crc_a, FrameError):
    """Read only verified Type 2 user memory with bounded read-only retries.

    An RF CRC failure is not successful data. Always report the exact stage
    and page; the recovered driver's transceive cleans up failed exchanges.
    """
    def stage_error(stage, exc, tries):
        state = getattr(chip, "rf_state", {}) or {}
        flags = ", ".join(
            f"{key}={state[key]}" for key in
            ("irq_main", "irq_error", "fifo_status", "fifo_size", "rssi_am")
            if key in state)
        return RuntimeError(
            f"{stage}: {exc} (attempts={tries}"
            + (f"; {flags}" if flags else "")
            + "). Try moving the tag slightly or checking antenna wiring.")

    def retry(stage, operation, attempts=3):
        error = None
        for _ in range(attempts):
            try:
                return operation()
            except (FrameError, TimeoutError, OSError) as exc:
                error = exc
        raise stage_error(stage, error, attempts) from error

    uid, info = retry("NFC-A anticollision/selection", lambda: poll_a(chip))
    if len(uid) != 14 or info["sak"] != 0:
        raise ValueError("Not a supported seven-byte ISO14443-A Type 2 tag")

    def read4(n):
        def once():
            result = receive(chip, bytes((0x30, n)), checksum=crc_a)
            if len(result) != 16:
                raise FrameError("size", "Type 2 READ did not return 16 bytes")
            return result
        return retry(f"Type 2 READ page {n}", once)

    head = read4(0)
    if (head[:3] + head[4:8]).hex().upper() != uid:
        raise ValueError("Tag UID does not match manufacturer pages")
    cc = head[12:16]
    if cc[0] != 0xE1 or cc[1] >> 4 != 1 or not cc[2]:
        raise ValueError("No supported NFC Forum Type 2 capability container")
    capacity = cc[2] * 8
    if capacity < 16 or capacity > 1008 or capacity % 8 or (4 + capacity // 4) > 256:
        raise ValueError(f"Unsupported Type 2 CC capacity: {capacity} bytes")
    if cc[3] != 0:
        raise ValueError("Capability Container indicates restricted access; refusing write")
    # A locked tag is still worth inspecting. Lock status is enforced in
    # the write path instead of refusing read-only inspection.
    static_lock_bytes = bytes(head[10:12])
    data = bytearray()
    for page in range(4, 4 + capacity // 4, 4):
        data.extend(read4(page))
    # Optional extras: GET_VERSION and single-page FAST_READ. These are
    # purely read-only; never fetch password or PACK pages.
    version = None
    config_pages = {}
    dynamic_lock_bytes = None
    try:
        candidate = receive(chip, bytes((0x60,)), checksum=crc_a)
        if len(candidate) == 8:
            version = candidate
    except (FrameError, TimeoutError, OSError):
        pass
    from tag_workshop_access import MODELS, model_for
    candidate_snapshot = {"capacity": capacity, "version": version}
    if model_for(candidate_snapshot):
        dyn, auth_page, access_page = MODELS[capacity][1:4]

        def read_one_page(n):
            # FAST_READ 0x3A, start=end=n, returns exactly four bytes;
            # avoids reading neighboring password/PACK pages.
            try:
                answer = receive(chip, bytes((0x3A, n, n)), checksum=crc_a)
                return answer if len(answer) == 4 else None
            except (FrameError, TimeoutError, OSError):
                return None

        lock_page = read_one_page(dyn)
        if lock_page is not None:
            dynamic_lock_bytes = lock_page[:3]
        cfg_one = read_one_page(auth_page)
        if cfg_one is not None:
            config_pages["auth0"] = cfg_one[3]
        cfg_two = read_one_page(access_page)
        if cfg_two is not None:
            config_pages["access"] = cfg_two[0]
    return {"uid": uid, "atqa": info.get("atqa"), "sak": info["sak"],
            "cc": cc.hex().upper(), "capacity": capacity,
            "data": bytes(data[:capacity]),
            "static_locks": static_lock_bytes.hex().upper(),
            "static_lock_bytes": static_lock_bytes,
            "dynamic_lock_bytes": dynamic_lock_bytes,
            "config_pages": config_pages, "version": version}


def perform(action, *, expected_uid=None, expected_data=None, new_data=None,
            backup_file=None, raw_transfer=False):
    from smbus2 import SMBus
    configure, poll_a, crc_a, receive, Reader, reader_lock, FrameError = driver()
    with reader_lock("i2c-1"), SMBus(1) as bus:
        chip = Reader(bus)
        try:
            chip.initialize(configure=lambda reader: configure(reader, "NFC-A"))
            result = read_all(chip, poll_a, receive, crc_a, FrameError)
            if action == "read":
                return result
            if action != "write":
                raise ValueError("Unknown workshop action")
            if result["uid"] != expected_uid:
                raise RuntimeError("Different tag detected. No changes made.")
            if result["data"] != expected_data:
                raise RuntimeError("Tag memory changed since edit was prepared. No changes made.")
            if not isinstance(new_data, bytes) or len(new_data) != result["capacity"]:
                raise ValueError("Replacement image does not match tag capacity")
            if not backup_file or not Path(backup_file).is_file():
                raise RuntimeError("Original backup missing; no changes made")
            # Inspect locks/protection BEFORE any physical write. If we
            # cannot read the status, fail closed rather than guess.
            if (result.get("static_lock_bytes") != bytes((0, 0))
                    or result.get("dynamic_lock_bytes") != bytes((0, 0, 0))):
                raise RuntimeError(
                    "Tag lock bits are set or unavailable. Inspect Access Matrix; no write attempted.")
            cfg = result.get("config_pages") or {}
            if cfg.get("auth0") is None or cfg.get("access") is None:
                raise RuntimeError(
                    "Protection configuration could not be read. No write attempted.")
            if cfg["auth0"] != 0xFF and cfg["auth0"] < 4 + result["capacity"] // 4:
                raise RuntimeError(
                    f"Tag user memory may be password protected from page {cfg['auth0']}. No write attempted.")
            # CC size alone does not establish the location of lock and
            # configuration bytes. Only enable physical writes for precisely
            # identified NXP NTAG21x geometry; unfamiliar tags stay readable.
            try:
                version = receive(chip, bytes((0x60,)), checksum=crc_a)
            except (OSError, TimeoutError, FrameError) as exc:
                raise RuntimeError(
                    f"WRITE preflight GET_VERSION (0x60) failed: {exc}. "
                    "No pages were written.") from exc
            supported = {0x0F: ("NTAG213", 144),
                         0x11: ("NTAG215", 496),
                         0x13: ("NTAG216", 872)}
            if (len(version) != 8 or
                version[:6] != bytes.fromhex("000404020100") or
                version[7] != 0x03 or
                version[6] not in supported):
                raise RuntimeError("Unknown Type 2 chip: user memory can be read, but writing is not yet verified safe")
            chip_name, known_capacity = supported[version[6]]
            if result["capacity"] != known_capacity:
                raise RuntimeError(
                    f"{chip_name} CC says {result['capacity']} bytes, expected {known_capacity}; write refused")
            # Known standard Type 2 NDEF TLV only. Writing arbitrary bytes,
            # UID pages, lock pages and card emulation aren't supported.
            if raw_transfer:
                from tag_workshop_raw import transfer_plan
                transfer_plan(result["data"], new_data)
            else:
                from tag_workshop_ndef import parse
                parse(result["data"])
                parse(new_data)
            if result["data"] == new_data:
                return {**result, "written": 0}
            def verify_header():
                try:
                    fresh = receive(chip, bytes((0x30, 0x00)), checksum=crc_a)
                except (FrameError, TimeoutError, OSError) as exc:
                    raise RuntimeError(
                        f"WRITE preflight UID recheck failed: {exc}. "
                        "Cannot verify destination tag.") from exc
                if (fresh[:3] + fresh[4:8]).hex().upper() != expected_uid:
                    raise RuntimeError("Tag swapped during write; aborting")
            def write_page(page, payload):
                if not 4 <= page < 4 + result["capacity"] // 4 or len(payload) != 4:
                    raise RuntimeError("Protected/out-of-range write refused")
                verify_header()
                # WRITE returns a 4-bit ACK with no CRC. Depending on the
                # ST25R3916 receiver, the CRC IRQ can still be asserted despite
                # disabling no_crc_rx. Do not retry a possibly completed write.
                original_aux = chip.rd(0x0A)
                rf_error = None
                raw = b""
                fifo_status = 0
                try:
                    chip.wr(0x0A, original_aux | 0x80)
                    try:
                        raw, fifo_status, _ = chip.transceive(
                            bytes((0xA2, page)) + payload, .045,
                            tx_command=0xC4, check_errors=True, max_rx=4)
                    except (FrameError, TimeoutError, OSError) as exc:
                        rf_error = exc
                finally:
                    chip.wr(0x0A, original_aux)
                # Crucially, validate actual memory AFTER an ambiguous RF
                # response. Receiving a bad ACK does not mean the write failed.
                # Never issue the same write a second time automatically.
                try:
                    verify = receive(chip, bytes((0x30, page)), checksum=crc_a)
                except (FrameError, TimeoutError, OSError) as exc:
                    reason = str(rf_error) if rf_error else f"unexpected ACK raw={raw.hex()}"
                    raise RuntimeError(
                        f"WRITE page {page}: {reason}; subsequent read-back failed: {exc}. "
                        "Page state is UNKNOWN. Stop and re-read the tag before retrying."
                    ) from exc
                if len(verify) != 16:
                    raise RuntimeError(
                        f"WRITE page {page}: invalid read-back length {len(verify)}; "
                        "page state is UNKNOWN. Stop and re-read before retrying.")
                if verify[:4] != payload:
                    reason = str(rf_error) if rf_error else (
                        f"unexpected ACK raw={raw.hex()} fifo=0x{fifo_status:02X}")
                    raise RuntimeError(
                        f"WRITE page {page}: {reason}; read-back differs. "
                        f"Expected {payload.hex().upper()}, got {verify[:4].hex().upper()}. "
                        "No automatic retry was made.")
                if rf_error:
                    # The four bytes now match exactly. Do not let a CRC-less
                    # ACK failure incorrectly report that the write did not
                    # happen; the following pages still undergo verification.
                    print(f"WRITE page {page}: RF ACK error ({rf_error}), "
                          "but page read-back matched; proceeding.", flush=True)
                return True
            # Make TLV appear empty during the multi-page rewrite. This does
            # NOT make writing atomic; power loss can still partially modify it.
            # Page 4 is always committed LAST, after the remaining pages.
            old = result["data"]
            stage = b"\x03\x00\xFE\x00"
            write_page(4, stage)
            writes = 1
            for offset in range(4, len(new_data), 4):
                if old[offset:offset+4] != new_data[offset:offset+4]:
                    write_page(4 + offset // 4, new_data[offset:offset+4])
                    writes += 1
            write_page(4, new_data[:4])
            writes += 1
            # Keep the selected tag active; do not rely on an unverified
            # anticollision cycle after WRITE.
            verified = bytearray()
            for page in range(4, 4 + result["capacity"] // 4, 4):
                try:
                    verified.extend(receive(chip, bytes((0x30, page)), checksum=crc_a))
                except (FrameError, TimeoutError, OSError) as exc:
                    raise RuntimeError(f"WRITE final verification READ page {page} failed: {exc}") from exc
            verified = bytes(verified[:result["capacity"]])
            if verified != new_data:
                raise RuntimeError("Final byte-for-byte verification failed; tag may be partially written")
            return {**result, "data": verified, "written": writes}
        finally:
            try:
                chip.shutdown()
            except OSError:
                pass


def save_backup(snapshot):
    root = Path.home() / "pt35-nfc/workshop-backups"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = root / f"{stamp}-{snapshot['uid']}.json"
    payload = {k: (v.hex().upper() if isinstance(v, bytes) else v)
               for k, v in snapshot.items() if k != "data"}
    payload["memory_hex"] = snapshot["data"].hex().upper()
    with path.open("x", encoding="utf-8") as handle:
        os.chmod(path, 0o600)
        json.dump(payload, handle, indent=2)
    return path
