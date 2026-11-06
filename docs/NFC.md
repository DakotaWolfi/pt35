# PT35 NFC

The desktop app uses the modified M5Stack U216 ST25R3916 on `/dev/i2c-1`, address `0x50`, with direct 3.3 V power and polled IRQ status. It does not require an IRQ GPIO. Run as the desktop user with access to the I2C device and, for Iceman, its USB serial port. Reader operations share an advisory per-user device lock. Avoid running older NFC tools alongside this app because they do not acquire that lock.

## Install and update

From the checkout you want to run:

```sh
sudo apt install python3-tk python3-smbus2
bash scripts/install_nfc_gui.sh
```

Open **PT35 NFC Reader** in the application menu. The launcher runs the current checkout. Run the installer again if you move that checkout or switch to another worktree. The installer only writes the user's launcher and menu entry. Plain SSH normally has no graphical session. Use `python3 nfc/pt35_nfc.py status --backend internal` from SSH to check the reader without enabling RF.

To roll back, stop the app, switch to the earlier checkout, and run its GUI installer. Archive paths are independent of the checkout. The legacy entry points `nfc/nfcv_scan.py`, `nfc/nfcv_dump.py`, and `nfc/pt35_nfc.py` still run directly.

## Scan and archive

Start a scan, select a tag, then open Data or double-click its row. Data shows geometry, readable blocks, ASCII preview and read failures. Save captures the displayed record. Export offers JSON and a binary for a verified complete requested range. The Archive tab searches saved records, including labels. Set the **Onboard ST25DV UID** to filter only that UID. Use **Include configured onboard tag** to bypass the filter. Single-slot NFC-V inventory can still collide when two tags reply, so use one tag at a time during verification.

The archive defaults to `~/pt35-nfc/archive` for CLI and GUI. Keep existing files there. If earlier CLI captures live under `nfc/archive`, run `python3 nfc/pt35_nfc.py migrate-archive` to copy missing files. Original files and destination conflicts are preserved. `known_tonies.txt` in the archive accepts one confirmed UID per line. Auto-save for unverified NXP candidates is separate and off by default.

The archive has one current JSON record per protocol and identifier. A later degraded read retains the better capture and its timestamp, source and coverage while updating sighting metadata. Data from different reads is kept separate. JSON is published atomically under an archive lock. Newly verified binaries use content-addressed filenames and the record references the matching binary. Repeated reads retain at most one managed binary per tag after a successful save. Legacy files remain intact.

`requested_range_complete` requires all requested indices and consistent byte lengths. `addressable_memory_complete` also requires known geometry and an exact range covering it from block zero. System Information may provide geometry. NXP UID tag type `03` uses the published SLI-L/SLIX-L user-memory geometry when System Information is unavailable. Other tags default to a conservative eight-block probe when geometry is unknown. All-zero blocks are valid when framing, CRC, response flags and lengths agree. A timeout leaves the cause unknown. A tag-reported unavailable or locked block is recorded separately. Addressable user memory does not include protected configuration, passwords or authentication secrets.

## Verification status

| Backend / mode | Status |
| --- | --- |
| Internal NFC-V inventory and addressed read | Legacy path bench-proven. Changes in this branch require PT35 verification. |
| Internal NFC-A / NFC-B / NFC-F | Pending implementation and individual bench checks. |
| Proxmark3/Iceman selection and identification | Implemented for a matching, responsive client. PT35 USB/RF verification pending. |

Offline tests use synthetic frames and temporary archives.

```sh
python3 -m unittest discover -s tests -p 'test_nfc_offline.py' -v
```

### Raspberry Pi bench checklist

1. On the PT35 desktop, open the app. Check **Reader status**, then **Start** with the Internal backend. Confirm Start, Stop, and window close work with no tag, a tag held in place, and a tag removed during a read. After Stop, immediately start a second scan and confirm it can use the same reader.
2. Scan one Tonie, one blank ISO15693 tag, and the onboard ST25DV. Compare the Tonie UID and blocks with a known-good read. On a blank tag, confirm valid zero blocks display as readable. Configure the exact onboard UID and verify both filter settings. If geometry is unavailable, confirm coverage stays limited to the requested range.
3. Save a good capture, then interrupt a repeat read and save the partial result. Verify the good capture still opens from Archive, labels remain intact, and the binary size matches its recorded range. Confirm the local archive was available before and after launching.
4. Verify RF is off after Stop. With no scanner running, read ST25R3916 Operation Control using the read-only command below. TX/RX bits `0x48` must both be clear. Run the status check and note whether buttons, LEDs, fan and Remote Eye still behave normally.
5. Send back the per-tag coverage/status, any error text and the Operation Control byte. Leave out tag identifiers and captured bytes.

```sh
python3 nfc/pt35_nfc.py status --backend internal
python3 - <<'PY'
from smbus2 import SMBus, i2c_msg
with SMBus(1) as bus:
    value = i2c_msg.read(0x50, 1)
    bus.i2c_rdwr(i2c_msg.write(0x50, [0x42]), value)
    op = bytes(value)[0]
print(f'ST25R3916 operation control 0x{op:02X}, RF bits 0x{op & 0x48:02X}')
PY
```

References for the driver include the [ST25R3916 datasheet](https://www.st.com/resource/en/datasheet/st25r3916.pdf), [M5Stack stream decoder](https://github.com/m5stack/M5Unit-NFC/blob/471a6e02e8052264d39b3ac97005ce4de9d1cb91/src/nfc/v/nfcv.cpp), and [NXP SLIX-L datasheet](https://www.nxp.com/docs/en/data-sheet/SL2S5002_SL2S5102.pdf).
