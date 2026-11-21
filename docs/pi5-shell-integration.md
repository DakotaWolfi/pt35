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

## Updated launcher / input / LED stage

Run: cd ~/pt35-migration && git pull && bash scripts/install_pi5_shell.sh
Creates FMI Tools launcher tile (pin with Y), Settings > FMI Tools submenu, conditional Remote Eye / Collar Pet apps, and an LED Controls submenu.
Settings includes Wolf menu icon and Normal menu icon. Wolf option is blocked until our custom taskbar binary is installed.
Build and install wolf: bash scripts/patch_wolf_taskbar.sh --install (requires Rust >=1.82; backs up installed bar binary; logout/login afterward).

The legacy pt35-buttons.service must not run alongside native PocketTerm35 input bindings. Check: systemctl --user status pt35-buttons.service
To stop it: systemctl --user disable --now pt35-buttons.service
Stock keyboard A/B/X/Y/L/R are indistinguishable from typed letters. Upstream patched firmware makes them distinctive (but flash only after explicit decision); L closes a window, R switches mouse mode, A/B click in mouse mode.

## Pi5 LED test (manual, opt-in)
Install scripts/install_pi5_leds.sh only after verifying 16 WS2812 pixels on BCM GPIO18 and /dev/pio0 presence. Uses Adafruit RP1 PIO library; does not enable/start the service automatically.
To bench test: systemctl --user start pt35-leds-pi5
Then: ~/.local/bin/pt35-ledctl status ; ~/.local/bin/pt35-ledctl color 0 10 0 ; ~/.local/bin/pt35-ledctl off
Stop: systemctl --user stop pt35-leds-pi5
Default output OFF and brightness capped at 15%. Requires common ground and adequate 5 V LED supply; a data level shifter may be needed.
