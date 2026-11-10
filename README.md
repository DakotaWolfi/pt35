# PT35 Pocket Terminal

Raspberry Pi 4B-based pocket terminal. This repository is the home for the PT35's device-specific software, services, button mappings, hardware notes, and integrated NFC tooling.

## Touch launcher (R button)

The `tools/pt35_launcher.py` presents a fixed **2-column × 3-row** home grid with five tool tiles and Exit, with status/help text beneath the buttons. It is a dark touchscreen launcher for **NFC Tag**, **NFC Reader**, **Spectrum Analyzer**, **LED Test**, and **LRA Haptic Test**. It uses only the repo checkout; no new hardware service. The Spectrum Analyzer now opens a native Tk touchscreen GUI; the original terminal-based AS7341 analyzer remains in `tools/pt35_tools.py` as a fallback. The NFC Reader launches the existing Tk NFC GUI; there is no second RF scanning implementation.

For a first bench check from an active PT35 desktop session:

```bash
cd ~/pt35-nfc-bench
python3 -m py_compile tools/pt35_launcher.py
python3 -m unittest discover -s tests -p 'test_pt35_launcher.py' -v
python3 tools/pt35_launcher.py --windowed
```

To create the launchers, and **explicitly rebind R** from the old `~/.local/bin/pt35-nfc-menu` entrypoint to the new launcher (with a timestamped backup of the original file):

```bash
bash scripts/install_pt35_launcher.sh --bind-r
```

The button service already launches `pt35-nfc-menu` on R, so the installer normally needs **no service restart**. It does *not* install or restart `pt35-leds.service` or `pt35-buttons.service`. If you have overridden `PT35_NFC_CMD` in the live button environment, that override must be inspected separately. Repeated R presses do not start multiple launcher windows.

To leave the R mapping unchanged, install the launcher only with `--no-bind-r`. If you need the prior R behavior, restore the exact file printed as the backup by the installer (for example `cp -a ~/.local/bin/pt35-nfc-menu.backup.TIMESTAMP ~/.local/bin/pt35-nfc-menu`). Check the file's real path first; `TIMESTAMP` is not a literal filename.

**NFC Tag** now opens `nfc/pt35_i2c_tag_gui.py`, a touch-friendly rewrite of the installed `PT35_XIAO_NFC_Controls_v1.4` app, **not the RF archive**. It uses an isolated I²C backend in `nfc/pt35_i2c_tag.py` and preserves v1.4 read/verify, format-if-blank, CollarPet/PT35 info, Telegram, GitHub, and custom URI/text NDEF writing. Every write needs confirmation, saves a private 512-byte before-image in `~/.local/share/pt35-nfc-tag-backups/`, enforces bounded memory operations and validates the final NDEF data. It never writes system-memory I²C address 0x57 or invokes RF. No I²C writes happen merely by opening the page.

Test first via the PT35 desktop: `python3 nfc/pt35_i2c_tag_gui.py --windowed`. The old `~/.local/bin/pt35-nfc-menu` remains untouched until `bash scripts/install_pt35_launcher.sh --bind-r` is deliberately run; the installer backs up the old script. Tests: `python3 -m unittest discover -s tests -p 'test_pt35_i2c_tag.py' -v`. Hardware format/write functions remain **untested against the real PT35** until a deliberate, approved test with a blank tag. Avoid formatting an existing tag; the implementation refuses nonblank first-32-byte memory.

**Spectrum Analyzer** now opens `tools/as7341_gui.py` with **ten live gauges in order Clear (white), 415–680 nm (eight spectrum colors), NIR (pink)**, real relative raw counts, sample quality/I²C error status, a dim 4 mA illumination LED toggle, Pause/Resume and SMUX/CFG0 **Recover**. The original curses `tools/pt35_tools.py --device as7341` is retained as a known fallback and supplies the same sensor init and register-bank recovery. Tk never accesses I²C; its worker owns the sensor and turns the illumination LED off on normal exit. Flicker mode remains disabled because its memory-bank recovery is still under test. The UI does not claim calibrated irradiance or lux. **LED Test** provides dim temporary color flashes, pixel-order test and battery/status through `/run/pt35-led.sock` only. **LRA Haptic Test** calls the already installed `/usr/local/bin/lra_ctl` for status, fixed effects 1/10/47, and stop. It does not issue unbounded RTP commands. Hardware validation, small-screen layout and the previous old tag menu's specific functionality still need bench checks.

### AS7341 GUI test (from SSH, rendering on the PT35 screen)

Fetch the updated branch, then run `python3 -m unittest discover -s tests -p 'test_as7341_gui.py' -v` and `python3 -m unittest discover -s tests -p 'test_pt35_launcher.py' -v`. The AS7341 test uses fake sensor objects and does **not** validate real I²C response. From an active PT35 desktop shell:

```bash
cd ~/pt35-nfc-bench
~/as7341-env/bin/python tools/as7341_gui.py --windowed
```

If starting via SSH, use `DISPLAY=:0 XAUTHORITY="$HOME/.Xauthority" ~/as7341-env/bin/python tools/as7341_gui.py --windowed` for an X11 desktop; a Wayland desktop requires its existing session environment. The R-launcher entry points to the same GUI and does not require another installer run, since its user-level shim executes the repo checkout. No services or saved NFC data are changed.

Physical checklist: verify live eight-channel bars and Clear/NIR, LED on/off, Pause/Resume, Recover after intentionally requested reset, then Close (sensor LED off). Avoid running terminal AS7341 tool and new GUI simultaneously: both address I²C 0x39. The new GUI has **not** yet been validated on the real PT35.

### Emulation coverage and hardware boundaries

**Implemented:** Proxmark3 ISO15693 including the existing custom SLIX-L firmware path (verified complete 4-byte-block memory image), and **new Proxmark3 LF EM410x ID-only** emulation from saved 10-hex-digit identifiers. Both require user confirmation, valid archived records and a 10-second software bound. LF simulation verifies Iceman `lf em 410x help` support and sends `lf em 410x sim --id UID`, then requests `hw break`. If hardware stop cannot be confirmed, use the physical PM3 button and verify RF has ceased. No flash, raw tag writing or service restart is performed.

**Internal ST25R3916:** ST's datasheet confirms **NFC-A and NFC-F card emulation/target mode in silicon**; its NFC-V and NFC-B interfaces are reader-only. The PT35's custom Python I²C driver currently implements only initiator/reader polling; it has **no timed target-mode receive/response state machine, activation IRQ wiring or verified RF shutdown sequence**. Therefore, the internal target modes are documented but **not enabled** by this change. Installing an untested card-emulation register profile on the actively used reader would risk disrupting currently working scans. The onboard ST25DV is a separate genuine Type-5 NFC tag and can present its current NDEF contents using the I²C tag app. To implement internal Type-4 NFC-A and NFC-F targets, first validate IRQ/status polling on the M5Stack unit, RF field off on exit and timing against a known reader, then build separate non-invasive target backend.

**PM3 NTAG/Ultralight, MIFARE Classic and FeliCa:** Iceman exposes additional emulator commands on many builds, but PT35's existing captures are not automatically sufficient. The internal NTAG read deliberately archives only **user pages starting at page 4**, omitting original UID/manufacturer, lock and configuration pages. Those cannot be advertised as full-tag images. NFC-A/B/F scanning may contain only identifiers, not the full data and behavior required by their respective card types. The UI explains these limitations rather than offering a misleading or unsafe "clone" action. Full archive format and emulator capability discovery are follow-up tasks, preserving the custom SLIX-L firmware.

### Possible Tonies metadata catalog

NFC Reader **Tools → Possible Tonies catalog** indexes observed **NXP ISO15693 (`E004…`) UIDs** in `~/pt35-nfc/archive/possible_tonies.json` after an ordinary archived scan, deduplicating by UID. An NXP manufacturer prefix **does not prove the tag is a Tonie**: entries remain `possible_tonie` unless their UIDs are explicitly present in the pre-existing locally maintained `known_tonies.txt`. Identified ordinary NDEF/business-card captures are omitted. No scan writes to the user's TeddyCloud, changes a tag, or fetches/downloads audio.

The toolbox provides **Scan saved NFC archives** (incremental, preserves curated metadata), **Export candidate UIDs (metadata only)** (explicit confirmation and separate `~/pt35-nfc/exports/possible_tonies-share.json`), and **Export verified TeddyCloud metadata** (`~/pt35-nfc/exports/tonies.custom.json`). The public candidate export contains only UID, technology, vendor, candidate status and evidence. **A UID may still identify or function as a simple access credential: review before sharing.** It never includes tag memory, passwords, RF logs, visit timestamps, TAF or audio.

TeddyCloud's `tonies.json` / `tonies.custom.json` is **not a UID database**: its model, `audio_id` and 40-hex SHA1 hash belong to actual Tonie/TAF content. The custom-format export includes **only** candidate entries explicitly enriched under a `teddycloud` object in the local catalog with a validated nonempty `model`, matched `audio_id` and `hash` lists. Values are **not guessed** from an NXP UID. If no independently verified content metadata has been added, the export will correctly be `[]`; do not load an empty export over an existing curated TeddyCloud file. The PT35 does **not** modify `tonies.custom.json` on the TeddyCloud server or its official `tonies.json`.

CLI (no RF required):
```bash
python3 nfc/pt35_nfc.py tonies-index
python3 nfc/pt35_nfc.py tonies-share
python3 nfc/pt35_nfc.py tonies-teddy-export
python3 -m unittest discover -s tests -p 'test_nfc_tonies.py' -v
```

## NFC (work in progress)
- Internal M5Stack ST25R3916 on I2C bus 1, address 0x50; direct 3.3 V supply (board modified to bypass its original regulator); IRQ not connected.
- See the [NFC application guide](docs/NFC.md) for installation, archive behavior and the PT35 hardware checklist.
- Optional Proxmark3/Iceman USB backend is under development.
- Never commit captured RFID/NFC dumps, passwords, hardware secrets, network credentials or private configuration.

## Related projects
- [Collar Pet](https://github.com/DakotaWolfi/collar-pet) — Collar Pet firmware and ST25DV16K mailbox endpoint
- [Vision Pi](https://github.com/DakotaWolfi/vision_pi) — Remote Eye / wireless camera and viewer components

## Migration notes
The current working PT35 was configured manually. Before replacing files or installing services, make a filesystem inventory and preserve a local backup. Test changes in a separate working directory. PT35-specific programs belong here; Collar Pet and Vision code should be copied to their repositories only after comparison with the versions already committed.

The NFC launcher runs from the Git checkout and uses the existing `~/pt35-nfc/archive`.
