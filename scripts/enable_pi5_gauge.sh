#!/usr/bin/env bash
# Opt-in MAX17048 kernel power_supply integration for PocketTerm35-OS.
# Does not alter other I2C devices, button firmware, or LED/fan setup.
set -euo pipefail
CONFIG=/boot/firmware/config.txt
OVERLAY=/boot/firmware/overlays/pt35-max17048.dtbo
if [[ "$(id -u)" == 0 ]]; then echo "Run as jenna, without sudo"; exit 1; fi
if grep -q '^dtoverlay=pt35-max17048' "$CONFIG"; then
  echo "Overlay already configured. Reboot if needed."; exit 0
fi
echo "WARNING: intended ONLY for a confirmed MAX17048 at I2C address 0x36."
echo "If your chip is MAX17055 or another model, STOP and choose its driver instead."
read -r -p "Type MAX17048 to add this overlay: " ANSWER
[[ "$ANSWER" == "MAX17048" ]] || { echo "Cancelled"; exit 1; }
if ! command -v dtc >/dev/null; then sudo apt-get install -y device-tree-compiler; fi
TEMP="$(mktemp -d)"
trap 'rm -rf "$TEMP"' EXIT
cat > "$TEMP/gauge.dts" <<'DTS'
/dts-v1/;
/plugin/;

/ {
    compatible = "brcm,bcm2712";
    fragment@0 {
        target = <&i2c1>;
        __overlay__ {
            pt35_fuel_gauge: fuel-gauge@36 {
                compatible = "maxim,max17048";
                reg = <0x36>;
                status = "okay";
            };
        };
    };
};
DTS
dtc -@ -I dts -O dtb -o "$TEMP/pt35-max17048.dtbo" "$TEMP/gauge.dts"
sudo cp -a "$CONFIG" "$CONFIG.pt35-gauge.$(date +%Y%m%d-%H%M%S).bak"
sudo install -m 644 "$TEMP/pt35-max17048.dtbo" "$OVERLAY"
printf '\n# PT35 MAX17048 power_supply for PocketTerm35 desktop\ndtoverlay=pt35-max17048\n' | sudo tee -a "$CONFIG" >/dev/null
echo "Overlay installed. Reboot, then inspect:"
echo "  ls /sys/class/power_supply/"
echo "  cat /sys/class/power_supply/*/capacity"
echo "If sysfs Battery appears, PocketTerm35-OS should show it on its taskbar."
echo "To undo: remove dtoverlay=pt35-max17048 from config.txt and reboot."
