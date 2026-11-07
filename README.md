# PT35 Pocket Terminal

Raspberry Pi 4B-based pocket terminal. This repository is the home for the PT35's device-specific software, services, button mappings, hardware notes, and integrated NFC tooling.

## Touch launcher (R button)

The new `tools/pt35_launcher.py` is an opt-in dark touchscreen launcher for **NFC Tag**, **NFC Reader**, **Spectrum Analyzer**, and **LED Test**. It uses only the repo checkout; no new hardware service. It preserves the existing terminal-based AS7341 analyzer and launches it in a graphical terminal. The NFC Reader launches the existing Tk NFC GUI; there is no second RF scanning implementation.

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

**NFC Tag** currently provides a read-only overview of the onboard ST25DV and recent locally archived tags; it deliberately does **not** reproduce unverified ST25DV memory/configuration writes from the old tag menu. It is a new foundation for further UI work. **Spectrum Analyzer** retains the existing trusted curses AS7341 tool for now; a native graphical spectrum redesign is a separate enhancement. **LED Test** provides dim temporary color flashes, pixel-order test and battery/status through `/run/pt35-led.sock` only. Hardware validation, small-screen layout and the previous old tag menu's specific functionality still need bench checks.

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
