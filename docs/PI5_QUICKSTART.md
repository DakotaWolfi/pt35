# PT35 Pi 5: one-entry installation on a spare microSD card

**Status:** Automated software baseline; hardware-dependent components still require testing.
Use a fresh **Raspberry Pi OS Trixie 64-bit Desktop** microSD card. The existing
Pi 4 PT35 card can remain untouched. Connect a suitable Pi 5 power supply.
Do not connect PT35 peripherals until their wiring and power rails are verified.

## Initial bootstrap (three commands)

Open a terminal on the Pi 5, logged in as your regular desktop user:

```bash
sudo apt update && sudo apt install -y git
git clone -b feature/pi5-staged-install https://github.com/DakotaWolfi/pt35.git ~/pt35
bash ~/pt35/bootstrap_pi5.sh
```

The installer updates the OS (including a full-upgrade), installs packages,
enables I2C, fetches the Collar Pet and Vision source repositories, installs
PT35 NFC tools and GUI, the button service, Collar Pet dashboard, link helpers
and PetMind UI. The button daemon is staged, but not started automatically
because the USB controller may not yet be connected. The Vision Pi repository
is cloned as a source dependency only; its headset runtime is **not** installed
or started on the PT35.

Reboot after installation:

```bash
sudo reboot
```

Then check:

```bash
bash ~/pt35/scripts/pi5_doctor.sh
```

Once the gamepad and display are connected and behaving correctly, enable:

```bash
systemctl --user enable --now pt35-buttons.service
```

To pair Collar Pet over SSH (one time, interactive):

```bash
~/.local/bin/cp-pair-ssh
```

## Subsequent updates

```bash
bash ~/pt35/bootstrap_pi5.sh
```

Optional flags: `--no-upgrade` skips the apt full-upgrade; `--enable-buttons`
enables the buttons service for the next user session. The bootstrap will
refuse to overwrite local edits in the PT35 checkout or the Collar Pet checkout.
Sensitive pairing keys and locally collected NFC archives are not stored in GitHub.

## Known unfinished Pi 5 migration work

- **LEDs:** The old GPIO12 WS2812 daemon uses Pi 4 DMA code, not a validated
  Pi 5 RP1 backend. It is not installed or enabled.
- **MAX17048:** The existing overlay specifically targets BCM2711. The Pi 5
  version must be validated before installation.
- **LRA:** Code is present (`scripts/setup_lra.sh`), but the physical module
  and bus must be verified first. It is not automatically enabled.
- **Fan:** The Pi 5 official Active Cooler runs via firmware control; old
  GPIO17 / 12 V fan control is deliberately not installed.
- **Remote Eye and customized PT35 desktop:** Current code in GitHub does not
  fully reproduce all manual changes and local services on the running Pi 4.
  Compare the live installation before removing the Pi 4 board.

Reinstalling this software does **not** restore device-local Wi-Fi credentials,
SSH private keys, custom system-level startup changes, or hardware firmware.

## Sources

- PT35: https://github.com/DakotaWolfi/pt35
- Collar Pet: https://github.com/DakotaWolfi/collar-pet
- Vision Pi: https://github.com/DakotaWolfi/vision_pi
