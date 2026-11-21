# PT35 Pi 5: staged shell + hardware integration

Target: Raspberry Pi 5 8 GB, Raspberry Pi OS Trixie 64-bit, therezor/PocketTerm35-OS 0.4.6.

## 1. Launcher and battery

- Run `bash scripts/install_pi5_shell.sh` to add existing PT35 apps without replacing upstream menu entries.
- MAX17048 confirmed by owner; address 0x36. Run `bash scripts/enable_pi5_gauge.sh` to install a reversible kernel power_supply overlay; reboot and check `cat /sys/class/power_supply/*/capacity`. PocketTerm35-OS reads this sysfs interface automatically.
- `python3 tools/pi5_battery_status.py` is a separate fallback diagnostic, not a live taskbar integration. Charging status requires another source if the gauge doesn't report it.

## 2. Wolf menu icon

The upstream taskbar only supports `skull` or `bars`; unknown values draw the skull. Run `bash scripts/patch_wolf_taskbar.sh`: patch source in `~/pt35-wolf-source`, add a 15x16 wolf and set `~/.config/pt35/theme.toml` to wolf. Building requires Rust. The script deliberately does not replace the installed binary; it prints the explicit backup/install commands after a successful build. Test only on the Pi after the desktop boots correctly.

## 3. DRV2605L haptics (I2C 0x5A)

- Existing source: `scripts/setup_lra.sh` installs `/usr/local/bin/lra_ctl`.
- After confirming I2C and all devices, install and test manually: `sudo bash scripts/setup_lra.sh`, then `lra_ctl status` and `lra_ctl play 1`.
- No systemd daemon required for an I2C-driven ROM effect. Later, desktop startup/notifications or our LED service can call `lra_ctl play EFFECT`.
- Do **not** run `pt35-buttons` on the Pi5 until input events are reconciled with PocketTerm35-OS; its current code expects a different gamepad-like input device.

## 4. NeoPixels

- The old `services/pt35_led_daemon.py` assumes LED_PIN=12 (BCM GPIO12, not physical pin 12) and `rpi_ws281x`. The Pi5 LED output is planned for **BCM GPIO18 / physical pin 12**, pending hardware wiring confirmation.
- Neither `scripts/setup_pt35_hardware.sh` nor `scripts/setup_fan.sh` should be run on Pi5: they include older pin assumptions and old fan controls. The Pi5 uses the official Active Cooler.
- `rpi_ws281x` may require a Pi5-specific driver or an alternate backend; test compatibility and signal timing **before** enabling any LED service. Prefer a backend abstraction while retaining the existing Unix socket commands `led_ctl idle|off|rainbow|battery|color|flash`.
- When the new backend is verified, install a Pi5-specific `pt35-leds.service`, initially disabled, then test manually before enabling at boot.
- Keep GPIO17 reserved for the haptic trigger wiring if still attached, and GPIO4 for GT911 touchscreen IRQ; verify hardware mapping rather than assuming these are unused.

## Validation after each stage

```sh
sudo i2cdetect -y 1
ls /sys/class/power_supply/
systemctl --user status pt35-buttons.service
systemctl status pt35-leds.service
```

No automatic LED, fan, keyboard firmware, or haptic hardware activation is included in the wolf/launcher scripts.
