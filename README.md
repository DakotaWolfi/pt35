# PT35 Pocket Terminal

Raspberry Pi 4B-based pocket terminal. This repository is the home for the PT35's device-specific software, services, button mappings, hardware notes, and integrated NFC tooling.

## Touch launcher (R button)

The new `tools/pt35_launcher.py` is an opt-in dark touchscreen launcher for **NFC Tag**, **NFC Reader**, **Spectrum Analyzer**, **LED Test**, and **LRA Haptic Test**. It uses only the repo checkout; no new hardware service. It preserves the existing terminal-based AS7341 analyzer and launches it in a graphical terminal. The NFC Reader launches the existing Tk NFC GUI; there is no second RF scanning implementation.

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

**Spectrum Analyzer** retains the existing trusted curses AS7341 tool for now; a native graphical spectrum redesign is a separate enhancement. **LED Test** provides dim temporary color flashes, pixel-order test and battery/status through `/run/pt35-led.sock` only. **LRA Haptic Test** calls the already installed `/usr/local/bin/lra_ctl` for status, fixed effects 1/10/47, and stop. It does not issue unbounded RTP commands. Hardware validation, small-screen layout and the previous old tag menu's specific functionality still need bench checks.

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
