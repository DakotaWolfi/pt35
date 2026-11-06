# PT35 NFC — implementation handoff for ChatGPT Work

**Date:** 2026-11-06  
**Repository:** https://github.com/DakotaWolfi/pt35 (branch `main`)  
**Related repositories:** https://github.com/DakotaWolfi/vision_pi and https://github.com/DakotaWolfi/collar-pet  
**Objective:** Deliver a usable, standalone, touchscreen/mouse-friendly PT35 NFC/RFID application with automatic reader selection, broad supported-protocol reading, safe archive management, and optional Proxmark3 emulation tooling. **No claim of protocol support without successful hardware testing.**

## Operational baseline — preserve it

- PT35: Raspberry Pi 4B 8 GB; Debian 13 aarch64, kernel 6.18.50; Python 3.13.5.
- Built-in reader: modified M5Stack U216 ST25R3916, I2C `/dev/i2c-1`, address `0x50`, direct 3.3 V supply; **no IRQ GPIO**, so status polling is necessary. Do not assume unmodified breakout wiring, GPIOs, or SPI access.
- Same I2C bus also contains other active devices, including ST25DV16K at `0x2D`, `0x53`, `0x57`; AS7341 at `0x39`; battery monitor at `0x36` (kernel owned). Never reset the whole bus, write to unrelated addresses, or disturb live services.
- **Working** ISO15693 inventory code: `nfc/nfcv_scan.py` (`Chip`, `encode_vcd`, `crc15693`). Proven on real tags with CRC-checked UIDs from NXP and ST.
- ISO15693 addressed memory reads: `nfc/nfcv_dump.py` (`Reader`) and `nfc/pt35_nfc.py`; real 4-byte blocks read from Tonies. These paths need robustness improvements.
- Combined CLI: `nfc/pt35_nfc.py`. USB Proxmark3 detection; Iceman client currently not installed on Pi as of last status. USB serial presence (e.g. `/dev/ttyACM0`) **does not** prove PM3 access.
- GUI prototype: `nfc/pt35_nfc_gui.py`, Tkinter; desktop-launch installer `scripts/install_nfc_gui.sh`. Graphical session works on device; plain SSH often has neither `DISPLAY` nor `WAYLAND_DISPLAY`. Install creates `~/.local/share/applications/pt35-nfc.desktop` (app menu), not necessarily an icon on `~/Desktop`.
- Current local archive: `~/pt35-nfc/archive`. **Protect it**. Captured tag data, PM3 recordings, private network details, passwords, keys, and dumps must not be committed to PUBLIC GitHub. Repo `.gitignore` excludes archive/dump patterns.
- Existing PT35 programs and systemd services must continue to work (fan, LEDs, buttons, Remote Eye). No blanket replacement of executables, no stopping unrelated services.
- Use **stable filenames**. `nfcv_scan.py` must never become `nfcv_scan_v2.py` in deployment. Keep revisions in Git commit history and in-module version constants.

## Requested user-facing experience

One GUI launched locally from the PT35 desktop without SSH, usable via mouse/keyboard, adapted to PT35 screen dimensions:
1. Clear device status; auto backend selects **connected and responsive** Proxmark3/Iceman when present, else internal ST25R3916. User may force either backend. Explicitly report missing Iceman client, port failures, and what features each backend supports. USB unplug/replug should recover.
2. Live tag discovery with protocol, UID/identifier, vendor/technology if verified, signal/result states and readable content; do **not** label every NXP ISO15693 tag a confirmed Tonie.
3. Internal reader: ISO15693/NFC-V must stay fully functional, including inventory, addressed read, CRC validation, system-info/geometry, and memory dump. Extend to **NFC-A, NFC-B, NFC-F** only as hardware and published mode specifications permit, testing each independently. If a mode is unavailable over the modified 4-wire I2C interface, explain limitation instead of inventing support.
4. Proxmark3: use the **Iceman** client when installed/compatible; support HF and LF discovery, protocol-specific dumping via validated CLI commands, displaying logs/results, and appropriate device-capability handling. Build/install Iceman from the RfidResearchGroup/proxmark3 repository with hardware-specific configuration and compatibility checks; **never automatically flash firmware**.
5. Tag display: typed decoding for ISO15693 raw hex blocks, NDEF where present, ASCII/UTF-8 preview when appropriate, physical memory geometry, readable vs protected/failed blocks, CRC/error information, and optional known-chip details. Never infer tag validity from bytes being zero.
6. Archive: user can save any readable tag, auto-save **known Tonie UID matches** (and optionally NXP *candidate* tags with clear warnings); store original machine-readable record and binary dump **only when the claimed range is complete**. Keep scan timestamps and source/backend. Browse/search/inspect/export/archive from GUI.
7. **Read-only by default.** Writing, cloning, simulation, or password operations require explicit separate user intent and confirmations. Show supported PM3 emulation operations only where confirmed. Do not promise a Tonie clone: protected secrets/authentication and UID constraints can prevent it. ISO15693 emulation is not available as a supported ST25R3916 mode over the current I2C setup; PM3 supports experimental ISO15693 simulation.
8. Start/Stop buttons must work reliably with hung/absent tags, noisy RF, and disconnection. No unbounded retries and no UI thread blocking.

## Critical correctness issues to address before “complete”

- `nfc/pt35_nfc.py` `save_record()` currently preserves an existing record's blocks **only if the new record has no blocks**. A later *partial* scan with some blocks can replace a previous full read. Fix via immutable captures or a quality/coverage comparator; atomic filesystem writes (`tempfile`+rename), archive-lock strategy where needed. Preserve known-good metadata.
- `handle_tag()` may mark an arbitrary eight-block fallback as `requested_range_complete`, which is **not the same as a full-memory dump**. Introduce independent fields for requested range, known geometry, complete addressable memory, and verified/protected regions.
- Get System Information (`0x2B`) may fail on Tonie/ICODE SLIX-L; geometry unavailable is not proof of 8 blocks. Try manufacturer data-sheet-aware fallback / conservative block probing, distinguish actual out-of-range errors from timeouts and access-denied. Avoid aggressive scanning.
- `nfcv_dump.py` and combined app can save partial archives; treat all-zero bytes as valid **when** the RF frame passed CRC, response flags were successful, and size matches expected. Never reject solely because zero-filled.
- `nfcv_dump.py` `decode_response()` enumerates hard-coded candidate frame lengths. Make this robust and bounded with exact CRC/Manchester validation and error classification.
- `nfc/pt35_nfc_gui.py` presently starts CLI subprocess and parses its console output, not a structured event API. Refactor to JSON-lines event stream or backend/controller interface; reserve UI updates for Tk main thread. Do not run concurrent RF scans on the same hardware. Avoid thread/process leaks on close.
- `nfc/pt35_nfc_gui.py` uses `~/pt35-nfc/archive` intentionally to preserve older data, while CLI default is currently `HERE/archive`; centralize persistent archive path in one config and migrate non-destructively.
- Current GUI includes backend radio, archive list and raw JSON viewer but **not** full protocol classification, decoded data viewer, explicit manual save of already seen tag, backend capability panels, or protocol-specific PM3 actions.
- The USB Proxmark3 selection must validate both a true PM3 descriptor and a responsive matching Iceman client/firmware. Avoid treating any ttyACM as a PM3. A PM3 test failure should not block internal fallback.
- Scan worker shutdown: Ctrl+C signal to child and after timeout SIGTERM/SIGKILL as needed; verify RF shutdown on stop; don't leave the field enabled.

## Repository layout (existing)

```text
nfc/nfcv_scan.py         # real working I2C/ST25R3916 ISO15693
nfc/nfcv_dump.py         # addressed read + JSON/bin dump
nfc/pt35_nfc.py          # combined CLI + archive/backend selection
nfc/pt35_nfc_gui.py      # current Tkinter GUI prototype
scripts/install_nfc_gui.sh
services/                # live PT35 services copied for preservation
systemd/                 # related service definitions
```

Add proper module boundaries/tests under `nfc/` and `tests/` as appropriate without breaking legacy entrypoints.

## Delivery phases and acceptance gates

**Phase 1 — stabilize existing ISO15693 and GUI (mandatory):**
- Preserve all legacy entrypoints, archive files and running services.
- Tests: known-good 4-byte block with `00 00 00 00` passes; malformed Manchester / CRC error / timeout fails; uninterrupted inventory after failed reads; a later partial read **cannot overwrite** earlier full memory; unknown geometry cannot be marked full; repeated scans of same UID don't exhaust disk; PT35's own ST25DV may be excluded or included by selection.
- GUI Start/Stop and data-browser tests; desktop launcher installation test; explicitly show connected backend and faults.
- Real PT35 run with Tonie, blank ISO15693, and PT35 ST25DV; archive data confirmed.

**Phase 2 — internal protocol breadth:**
- Verify ST25R3916 chip control and published M5Stack library sequences for NFC-A, NFC-B, NFC-F (not just ISO15693). Implement inventory/detection and safe NDEF/user memory where available.
- Test on actual NFC-A/NTAG, NFC-B and NFC-F tags; mark each implemented/tested protocol distinctly. No untested “all protocols supported” label.

**Phase 3 — Proxmark3/Iceman:**
- Provide reproducible install script with confirmation before package installation; detect device and firmware incompatibilities; configurable PM3 client path and serial port.
- Test PM3 auto selection, unplug/replug recovery, HF/LF tag identification, supported dump formats, and **explicit/manual** simulation for supported formats (no auto-emulation).
- Never embed passwords, tag dumps, or radio credentials in Git.

**Phase 4 — polished release:**
- Screen-resolution-responsive UI with tabbed Scan / Data / Archive / Proxmark / Settings; sensible status indicator; error notifications; user-editable settings persisted safely; startup launcher and optional autostart (off by default).
- Documentation: supported-protocol matrix with Tested/Implemented/Not yet tested, install/update/rollback instructions, hardware pinout constraints, archive schema and migration, safety notes.
- GitHub PR (or a series of small focused commits) with offline unit tests and a PT35 hardware test checklist. Do not change `collar-pet` or `vision_pi` without comparing their source to actual remote-eye/collar components.

## Environment and workflow

- Connected GitHub repository can be edited through the GitHub integration. For actual PT35 hardware testing, ask user to run specific commands and paste output, or use Work's available remote access only **if explicitly available/authorized**; do not claim to have SSH access.
- User expects Git-based deployment: `cd ~/pt35 && git pull origin main`, then an explicit installer when needed; never distribute versioned ZIP scripts as primary delivery.
- Preserve live `~/pt35-nfc/` and archive while developing in `~/pt35/`.
- No root unless necessary, no firmware flashing unless specifically approved.
- An executable named `~/.local/bin/pt35-eye-control` exists but was missed in previous collection due to extensionless filename. It belongs to the Vision integration, **not** to the NFC release.

## Initial execution instruction for Work

Start by examining the repository and current tests. Produce a succinct plan, then implement and commit **Phase 1**, with tests and documentation, before expanding protocols. Ask for real tag/PM3 hardware results rather than guessing. Continue Phase 2/3 iteratively, clearly labeling unverified functionality.