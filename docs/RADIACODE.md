# PT35 · RadiaCode 103 companion (experimental)

This is a **read-only** live measurement and time-resolved spectrum recorder. The device is not reconfigured and **no radiation alarms are disabled**. The module is a separate GUI in the R-button launcher, or can be started directly. No PT35 system services, NFC readers, LEDs, fan, or archive are modified.

## Install only into an isolated checkout (no live deployment)

```sh
cd ~
git clone --branch feat/radiacode-103 https://github.com/DakotaWolfi/pt35.git pt35-radiacode-bench
cd ~/pt35-radiacode-bench
python3 -m venv --system-site-packages .venv
.venv/bin/pip install --upgrade radiacode
.venv/bin/python -m unittest discover -s tests -p 'test_radiacode_gui.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_pt35_launcher.py' -v
DISPLAY=:0 XAUTHORITY="$HOME/.Xauthority" .venv/bin/python tools/radiacode_gui.py --windowed
```

If `python3 -m venv` fails, install `python3-venv` only with owner approval. USB requires libusb access and appropriate permissions; BLE requires BlueZ and an available Bluetooth controller. The PT35 desktop session may require different X11/Wayland environment variables. Use `--windowed` for bench testing, omit it for full screen.

- USB first: `.venv/bin/python tools/radiacode_gui.py --windowed` (RadiaCode connected to USB).
- Bluetooth: `.venv/bin/python tools/radiacode_gui.py --bluetooth-mac AA:BB:CC:DD:EE:FF --windowed` (replace with address obtained locally; **never commit the address**).
- Set `--interval 1` for approximately 1-second *host-polled spectrum snapshots*. It is NOT guaranteed exact one-second spectrogram windows.
- Do not run the phone app and Bluetooth recorder concurrently. Disconnect the phone's active RadiaCode session first; pairing deletion should not normally be necessary.
- Close/Stop releases the connection. No auto-reconnect is included in this initial version.

## Data format and limitations

When Start is selected, the app writes under `~/.local/share/pt35/radiacode/` (or `--output PATH`):

- `*_telemetry.csv`: device-side timestamp when provided, host receive time, record class, count rate, dose-rate *protocol value*, errors, events, battery and temperature when available.
- `*_spectra.jsonl`: each cumulative 1024-channel spectrum, calibration, acquisition duration, optional nonnegative successive count difference, and timestamp **of the host poll**. Deltas are invalid when a reset or nonmonotonic measurement is detected. This is not a list of individually timestamped photon pulses.

Dose-rate protocol units have deliberately not been labeled µSv/h until verified with the device configuration; don't use the numeric field for dosimetry or alarm decisions without validating its units. Short intense airport X-ray exposures can overwhelm the detector and distort both count rates and spectra. The app does not calculate true peak scan dose or claim precise peak count rate.

## Bench checklist

1. Verify USB connection (prefer first), stable CPS reporting and changing cumulative spectrum.
2. Stop and reconnect; verify CSV/JSONL files are closed and new session files are created, not overwritten.
3. Disconnect USB while recording and verify a visible error; relaunch after reconnect.
4. Test Bluetooth after the phone app disconnects. If BLE is unavailable, keep USB as fallback.
5. Check GUI at 640×480 and current overscaled display; confirm physical Enter/Esc and touch Start/Stop/Close.
6. Validate dose-rate units and check timestamp drift against the official app on normal background.
7. Never intentionally X-ray the PT35, laptop or detector; avoid putting a live USB cable through security scanners.

**Status:** source implementation and offline unit-test source only; no physical PT35 test or detector connection verified.
