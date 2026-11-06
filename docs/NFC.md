# PT35 NFC

The desktop app uses the modified M5Stack U216 ST25R3916 on `/dev/i2c-1`, address `0x50`, with direct 3.3 V power and polled IRQ status. It does not require an IRQ GPIO. Run as the desktop user with access to the I2C device and, for Iceman, its USB serial port. Reader operations share an advisory per-user device lock. Avoid running older NFC tools alongside this app because they do not acquire that lock.

## Install and update

From the checkout you want to run:

```sh
sudo apt install python3-tk python3-smbus2
bash scripts/install_nfc_gui.sh
```

Open **PT35 NFC Reader** in the application menu. The launcher runs the current checkout. Run the installer again if you move that checkout or switch to another worktree. The installer writes the user's launcher and menu entry. Settings are saved only when you click **Save settings** and live at `~/.config/pt35-nfc/settings.json` by default. The app starts idle. To open it automatically on graphical login, run the installer with `--autostart`. Use `--no-autostart` to remove that login entry. Plain SSH normally has no graphical session. Use `python3 nfc/pt35_nfc.py status --backend internal` from SSH to check the reader without enabling RF.

To roll back, stop the app, switch to the earlier checkout, and run its GUI installer. Archive paths are independent of the checkout. The legacy entry points `nfc/nfcv_scan.py`, `nfc/nfcv_dump.py`, and `nfc/pt35_nfc.py` still run directly.

## Scan and archive

Start a scan, select a tag, then open Data or double-click its row. Data shows geometry, readable blocks, ASCII/UTF-8 previews, decoded NDEF text/URIs where available and read failures. Save captures the displayed record. Export offers JSON and a binary for a verified complete requested range. The Archive tab searches saved records, including labels. Set the **Onboard ST25DV UID** to filter only that UID. Use **Include configured onboard tag** to bypass the filter. Single-slot NFC-V inventory can still collide when two tags reply, so use one tag at a time during verification.

The archive defaults to `~/pt35-nfc/archive` for CLI and GUI. Keep existing files there. If earlier CLI captures live under `nfc/archive`, run `python3 nfc/pt35_nfc.py migrate-archive` to copy missing files. Original files and destination conflicts are preserved. `known_tonies.txt` in the archive accepts one confirmed UID per line. Auto-save for unverified NXP candidates is separate and off by default.

The archive has one current JSON record per protocol and identifier. A later degraded read retains the better capture and its timestamp, source and coverage while updating sighting metadata. Data from different reads is kept separate. JSON is published atomically under an archive lock. Newly verified binaries use content-addressed filenames and the record references the matching binary. Repeated reads retain at most one managed binary per tag after a successful save. Legacy files remain intact.

`requested_range_complete` requires all requested indices and consistent byte lengths. `addressable_memory_complete` also requires known geometry and an exact range covering it from block zero. System Information may provide geometry. NXP UID tag type `03` uses the published SLI-L/SLIX-L user-memory geometry when System Information is unavailable. Other tags default to a conservative eight-block probe when geometry is unknown. ST25DV16K/64K extended geometry is queried when standard System Information identifies that family. Automatic scans read at most 256 blocks. Request 512 or 2048 explicitly to read the larger addressable ranges. All-zero blocks are valid when framing, CRC, response flags and lengths agree. A timeout leaves the cause unknown. Tag-reported unavailable, locked and read-protected blocks are recorded separately. Addressable user memory does not include protected configuration, passwords or authentication secrets.

## Verification status

| Backend / mode | Status |
| --- | --- |
| Internal NFC-V inventory and addressed read | Legacy path bench-proven. Changes in this branch require PT35 verification. |
| Internal NFC-A | Implemented single-tag discovery and NTAG213/215/216 user-page reads. Bench check pending. |
| Internal NFC-B | Implemented one-slot ATQB/PUPI discovery. Bench check pending. |
| Internal NFC-F | Implemented one-slot FeliCa polling at 212 kbit/s. Bench check pending. |
| Proxmark3/Iceman HF and LF | Implemented Iceman identification logs and selected structured identifiers. PT35 USB/RF verification pending. |
| Proxmark3/Iceman ISO15693 memory | Implemented addressed raw reads with CRC verification and a 32-block cap per capture. Bench check pending. |
| Proxmark3/Iceman ISO15693 simulation | Experimental, explicit confirmation for a saved verified capture. Bench check pending. |

Offline tests use synthetic frames and temporary archives.

```sh
python3 -m unittest discover -s tests -p 'test_nfc*.py' -v
```

### Raspberry Pi bench checklist

1. On the PT35 desktop, open the app. Check **Reader status**, then **Start** with the Internal backend. Confirm Start, Stop, and window close work with no tag, a tag held in place, and a tag removed during a read. After Stop, immediately start a second scan and confirm it can use the same reader.
2. Scan one Tonie, one blank ISO15693 tag, and the onboard ST25DV. Compare the Tonie UID and blocks with a known-good read. On a blank tag, confirm valid zero blocks display as readable. Configure the exact onboard UID and verify both filter settings. If geometry is unavailable, confirm coverage stays limited to the requested range.
3. Save a good capture, then remove the tag during a repeat read and save the partial result. Verify the good capture still opens from Archive, labels remain intact, and the binary size matches its recorded range. Confirm the local archive was available before and after launching.
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

### Internal NFC-A, NFC-B and NFC-F checks

Select **Internal** and set **Internal protocol** in Settings, or run:

```sh
python3 nfc/pt35_nfc.py scan --backend internal --protocol NFC-A --tries 8
python3 nfc/pt35_nfc.py scan --backend internal --protocol NFC-B --tries 8
python3 nfc/pt35_nfc.py scan --backend internal --protocol NFC-F --tries 8
```

Use an NTAG213/215/216, an ISO14443-B card, and a FeliCa tag respectively. Compare the A UID, B PUPI or F IDm with an independent reader if available. Check the A user pages and NDEF preview with a known NDEF tag. B/F are discovery-only in this build. A resolves one UID at a time. B uses one REQB slot and F uses one 212 kbit/s polling slot. Retest NFC-V after changing modes. These use ST25R3916 hardware framing and polled status. Each mode needs a Pi bench result before it can be listed as tested.

Profile references are the upstream [NFC-A](https://github.com/m5stack/M5Unit-NFC/blob/471a6e02e8052264d39b3ac97005ce4de9d1cb91/src/unit/unit_ST25R3916_nfca.cpp), [NFC-B](https://github.com/m5stack/M5Unit-NFC/blob/471a6e02e8052264d39b3ac97005ce4de9d1cb91/src/unit/unit_ST25R3916_nfcb.cpp), and [NFC-F](https://github.com/m5stack/M5Unit-NFC/blob/471a6e02e8052264d39b3ac97005ce4de9d1cb91/src/unit/unit_ST25R3916_nfcf.cpp) implementations and [NXP's NTAG21x datasheet](https://www.nxp.com/docs/en/data-sheet/NTAG213_215_216.pdf).

### Proxmark3 and Iceman

First identify the exact Iceman revision already on your device, using its working client or your existing firmware records. Build a matching client from that revision and select the platform of the physical device. For example, after substituting your actual release tag or full commit hash:

```sh
bash scripts/install_iceman.sh --platform PM3GENERIC --rev YOUR_FIRMWARE_REVISION --install-deps
python3 nfc/pt35_nfc.py status --backend proxmark3
```

The installer asks before installing packages and builds the userspace client under `~/.local/lib/pt35-iceman`. It performs no device flashing. If you already have a matching client, use **Iceman client path** in Settings, `--client` or `PT35_PM3_CLIENT`. Port selection accepts a detected Proxmark3 device path or its stable `/dev/serial/by-id/` symlink. The app requires a PM3 USB descriptor, an Iceman hardware ping with matching content, and a matching firmware revision. An Iceman mismatch should be addressed by selecting or building the matching client. An unplugged PM3 falls back to the internal reader in Auto mode, and a later responsive PM3 is picked up during a watch.

In the **Proxmark** tab, select HF, LF or ISO15693 as the watch mode. **Identify HF / LF** shows Iceman's logs for both bands. Supported structured rows include NFC-A UID, NFC-B PUPI, NFC-F IDm, NFC-V UID and EM410x ID. Other detected protocols may appear only in the log. B PUPIs can be temporary and may change between sessions.

When the connected firmware advertises ISO15693 raw reads, select a tag and choose **Read selected ISO15693 memory**. This uses addressed, CRC-checked reads. For slower USB polling it limits each operation to 32 blocks. The CLI equivalent is `python3 nfc/pt35_nfc.py pm3-dump UID --save`. Discovery by itself is a metadata capture.

When the connected firmware advertises ISO15693 emulator load and simulate commands, **Simulate saved ISO15693 tag** requires explicit confirmation and a verified complete capture of 1–128 four-byte blocks. It loads a temporary Iceman image and runs a 10-second simulation. Use a bench tag and an independent reader you are authorized to test. Protected configuration and Tonie authentication are outside the image. Use Stop or the physical PM3 button to abort. RF shutdown and whether the independent reader can read the simulated blocks both require bench verification.

1. In Auto mode start without the PM3, attach it, then unplug and reconnect. Record the transitions and any client/firmware fault. With a forced PM3 backend, check that it waits for the device to return.
2. Try a known HF tag and a known LF tag with **Identify HF / LF**. Use the ISO15693 memory action on a small, blank tag and compare coverage and bytes locally with the internal reader.
3. If the PM3 exposes simulation, use a saved complete capture of that blank tag. Check that the other reader sees it only during the confirmed simulation and that a second run stops on request. Report device platform, firmware revision, operation statuses and any errors, omitting identifiers and tag contents.

Iceman references include the [command catalog](https://github.com/RfidResearchGroup/proxmark3/blob/f90d0d0bf923a5d2c3980e78066ab380e4585c8c/doc/commands.md), [ISO15693 client implementation](https://github.com/RfidResearchGroup/proxmark3/blob/f90d0d0bf923a5d2c3980e78066ab380e4585c8c/client/src/cmdhf15.c), and [client/platform build options](https://github.com/RfidResearchGroup/proxmark3/blob/f90d0d0bf923a5d2c3980e78066ab380e4585c8c/doc/md/Use_of_Proxmark/4_Advanced-compilation-parameters.md).
