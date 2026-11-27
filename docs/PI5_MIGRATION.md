# PT35 migration to Raspberry Pi 5 (staged / hardware validation required)

This path is **not** a fully working clone of the live PT35. The repository's README
says the current Pi 4 installation was configured partly by hand. The goal of this
installer is to prepare a clean Raspberry Pi OS Trixie 64-bit spare microSD card
without altering the existing Pi 4 setup.

## Preparation

1. Use a separate microSD card and install Raspberry Pi OS Trixie 64-bit with desktop.
2. Boot it on the Pi 5 with a suitable 5 V supply and its official Active Cooler.
3. Clone the repo and run `bash scripts/install_pi5.sh` as the normal user.
4. Reboot after I2C configuration. Keep the PT35's original Pi 4 SD card untouched.
5. Only connect the PT35 wiring after confirming 5 V regulation and available power
   under load. Check the physical fit and cooler airflow first.

## What the script does

- Confirms Pi 5, Trixie and arm64, then installs baseline tools.
- Enables I2C, with a backup of config.txt if it needs changing.
- Stages the evdev-based buttons user service (does **not** enable it).
- Copies NFC scripts, preserving pre-existing copies and NFC archives, and stages
  the Tkinter NFC GUI shortcut.
- Leaves the stock Pi 5 firmware-controlled Active Cooler alone.

## Important gaps before calling this a complete PT35 installation

- **WS2812 on GPIO12:** the Pi 4 service uses `rpi_ws281x` with Pi 4 DMA
  assumptions. Pi 5 requires a distinct RP1 approach; upstream's experimental
  `pi5` branch requires a kernel module and overlay. Do not enable the existing
  `pt35-leds.service` on Pi 5 without a tested replacement.
  See https://github.com/jgarff/rpi_ws281x/wiki/Raspberry-Pi-5-Support
- **MAX17048:** the existing `setup_pt35_hardware.sh` generates a BCM2711-only
  overlay. Do not run it on Pi 5. Test raw I2C address 0x36 first, then design
  and validate a Pi 5-safe driver/overlay.
- **Fan:** do not run `setup_fan.sh` or GPIO17 `fan-controller.service`. The
  official Pi 5 Active Cooler uses its dedicated fan connector and firmware control.
- **LRA:** `setup_lra.sh` can be run separately after verifying DRV2605L at
  0x5A on I2C bus 1. Do not assume the old motor is already mounted.
- **Buttons:** after detecting the PT35 gamepad in `/dev/input`, test the service
  manually: `python3 ~/.local/bin/pt35-buttons.py`. Then enable with
  `systemctl --user enable --now pt35-buttons.service`. Some button actions
  refer to programs from the Collar Pet and Vision repositories, which are not
  installed by this script.
- **NFC:** after confirming I2C connections and power modifications, test with
  `python3 ~/pt35-nfc/pt35_nfc.py status`. Never publish personal tag captures.
- **Other integrations:** installed Remote Eye control, startup splash,
  desktop layout, custom launchers, audio and external packages require inventory
  of the existing PT35. GitHub alone is not yet a complete backup of the system.

## Post-boot checks

```bash
cat /proc/device-tree/model
i2cdetect -y 1
vcgencmd get_throttled
systemctl --user status pt35-buttons.service
```

Do not connect 5 V modules to Pi GPIO signal inputs, and make sure the power
supply has headroom for the Pi 5 plus PT35 peripherals. The Pi 5 can draw more
peak current than the Pi 4B.
