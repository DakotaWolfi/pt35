# PT35 NFC

The desktop app uses the modified M5Stack U216 ST25R3916 on `/dev/i2c-1`, address `0x50`, with direct 3.3 V power and polled IRQ status. It does not require an IRQ GPIO. Run as the desktop user with access to the I2C device and, for Iceman, its USB serial port. Reader operations share an advisory per-user device lock. Avoid running older NFC tools alongside this app because they do not acquire that lock.

## Install and update

From the checkout you want to run:

```sh
sudo apt install python3-tk python3-smbus2
bash scripts/install_nfc_gui.sh
```

Open **PT35 NFC Reader** in the application menu. The launcher runs the current checkout. Run the installer again if you move that checkout or switch to another worktree. The installer writes the user's launcher and menu entry. Settings are saved only when you click **Save settings** and live at `~/.config/pt35-nfc/settings.json` by default. The app starts idle in full screen. Use **Tools → Toggle full screen** to switch to a window. To open it automatically on graphical login, run the installer with `--autostart`. Use `--no-autostart` to remove that login entry. Plain SSH normally has no graphical session. Use `python3 nfc/pt35_nfc.py status --backend internal` from SSH to check the reader without enabling RF.

To roll back, stop the app, switch to the earlier checkout, and run its GUI installer. Archive paths are independent of the checkout. The legacy entry points `nfc/nfcv_scan.py`, `nfc/nfcv_dump.py`, and `nfc/pt35_nfc.py` still run directly.

## Scan and archive

### Repeat reads, safe evidence history, and NDEF previews

Every successfully identified tag is now stored **locally**, even if the memory read is partial, failed, or discovery-only. RF-corrupted frames are never accepted as verified data; an unidentified failed inventory has no reliable UID to archive. Identical observations increment a scan count without duplicating capture files. Distinct observations are saved as immutable, per-tag `captures/<SHA-256>.json` evidence alongside the preferred `record.json` under `~/pt35-nfc/archive`. Do not publish this folder: it may contain private NFC UIDs, contact cards and memory contents.

The preferred capture is still selected conservatively. A new partial read cannot replace an existing complete verified capture. If **both captures have verified complete ranges but disagree in overlapping bytes**, the earlier preferred data stays intact; the differing later capture is retained separately and marked **changed verified**. A different partial read is marked **different partial**, not treated as proof of a changed tag. All captured blocks still require the ordinary protocol CRC, response and length checks. Nothing writes to the NFC tags.

Present a tag again after removal to trigger a new read. With the PM3, repeated held-tag reads are throttled (typically 15 seconds, or about 3 seconds following a partial/failed read) and `hf search` polling has a minimum one-second pause. The internal reader retains its previous absence-triggered reread handling. For PM3 NFC-V, a raw addressed memory read is attempted **only if that connected client advertises the ISO15693 raw command**, with a 32-block cap; PM3 NFC-A/B/F remain discovery-only. Internal NFC-A NTAG21x and NFC-V readers can capture memory for further decoding.

On the small touchscreen, open the latest tag or an Archive record, select **Scan history / compare captures**, and tap an observation to view classification, quality and bytes. A complete verified NFC NDEF message now previews text, URLs and a simple vCard business card (name, organization, phone, email, title, address and website). Unsupported NDEF formats remain visible as MIME/type descriptions, and partial records remain available as hex without being misidentified as valid NDEF.

Optional PT35 **top LED row** gives approximately 0.6-second status feedback: same capture = cyan/blue, improved coverage = lime, different fully verified bytes = purple, differing incomplete evidence = amber, new complete read = green, partial/failure = amber, general fault = red. The **bottom row** retains the tag technology color and available relative RSSI. The LED service and GPIO ownership remain unchanged; no live daemon installation/restart is performed by these commits. The GUI settings continue to default NFC LED effects to off.

Offline regression commands, before touching any live daemon:

```sh
cd ~/pt35-nfc-bench
python3 -m unittest discover -s tests -p 'test_nfc_capture_history.py' -v
python3 -m unittest discover -s tests -p 'test_nfc_led.py' -v
python3 -m unittest discover -s tests -p 'test_nfc_pm3.py' -v
```

**Caution:** Automatic local capture of all identified tags is a new behavior; review available disk space and sensitivity of NFC contents. Archive versions are additive and the scanner does not upload tag data to GitHub. Physical re-presentation timing, PM3 NFC-V block reads, NDEF card decoding and LED colors require actual PT35 bench testing.


Tap **Start scan** and tap the latest tag to open its coverage summary. **Hex / data** opens readable memory in scrollable pages. **Save tag** adds the capture to the archive. **Export** writes a JSON record or verified binary range to `~/pt35-nfc/exports`. In **Archive**, tap **Search tags** and type on the PT35’s built-in keyboard. The field is focused automatically. Press Enter to apply the search or Esc to cancel, then tap a result to inspect it.

In **Settings**, swipe vertically or use the wide scrollbar. **Back** and **Save settings** stay on screen. Backend, protocol and presets are tap selections. Tap a field to open a focused text input. Press Enter to accept the value or Esc to go back. Reader settings take effect on the next scan. NFC LED settings take effect when saved. Under **Appearance**, select **Dark** or **Light** to preview the theme and tap **Save settings** to keep it. Dark is the default. While a scan is running, **Stop scan** remains available on the other screens. Set the exact **Onboard ST25DV UID** to filter that one tag, or enable **Include onboard ST25DV** to see it. **Use latest ST tag as onboard UID** is available after detecting an ST tag. Use it only when you know which tag you just scanned.

The archive defaults to `~/pt35-nfc/archive` for CLI and GUI. Keep existing files there. If earlier CLI captures live under `nfc/archive`, run `python3 nfc/pt35_nfc.py migrate-archive` to copy missing files. Original files and destination conflicts are preserved. `known_tonies.txt` in the archive accepts one confirmed UID per line. Auto-save for unverified NXP candidates is separate and off by default.

The archive has one current JSON record per protocol and identifier. A later degraded read retains the better capture and its timestamp, source and coverage while updating sighting metadata. Data from different reads is kept separate. JSON is published atomically under an archive lock. Newly verified binaries use content-addressed filenames and the record references the matching binary. Repeated reads retain at most one managed binary per tag after a successful save. Legacy files remain intact.

`requested_range_complete` requires all requested indices and consistent byte lengths. `addressable_memory_complete` also requires known geometry and an exact range covering it from block zero. System Information may provide geometry. NXP UID tag type `03` uses the published SLI-L/SLIX-L user-memory geometry when System Information is unavailable. Other tags default to a conservative eight-block probe when geometry is unknown. ST25DV16K/64K extended geometry is queried when standard System Information identifies that family. Auto reads at most 32 known blocks or probes eight when geometry is unknown. Choose **All known** (CLI `--blocks -1`) or enter a specific count for larger ranges. With an unverified size, **All known** still probes eight. All-zero blocks are valid when framing, CRC, response flags and lengths agree. A timeout leaves the cause unknown. Tag-reported unavailable, locked and read-protected blocks are recorded separately. When geometry is known, the reader tries bounded multi-block reads, then falls back to addressed single blocks if a batch fails. Use `--single-block` to compare against the single-block path. Addressable user memory does not include protected configuration, passwords or authentication secrets.

## Automatic reader and protocol detection

**Reader backend → Auto** starts with the internal reader and probes USB Proxmark3 in the background during a watch. It stops the internal RF field before switching to a responsive Proxmark3 using a compatible Iceman client; differing source revisions are reported, not rejected. A disconnect returns the watch to the internal reader. Leave the client and port settings blank for discovery. The home screen distinguishes missing device, missing client, permission failure, firmware mismatch, and connection.

**Internal protocol → Auto** is the default for fresh settings. It polls NFC-V, NFC-A, NFC-B, and NFC-F in order, reinitializing the ST25R3916 when the technology changes. A detected tag is read in that mode before the sweep continues. NFC-B and NFC-F report discovery only. Existing saved manual choices stay selected until you change them. For troubleshooting use a manual mode or set a different Auto order with `--poll-order ISO15693,NFC-A,NFC-B,NFC-F` (list each mode once).

## Verification status

| Backend / mode | Status |
| --- | --- |
| Internal NFC-V inventory and addressed read | The prior PR failed physical checks. FIFO recovery, masked inventory and multi-block fallback passed synthetic tests. Real inventory, reads and RF shutdown await a PT35 retest. |
| Touch and keyboard GUI | Synthetic tap, swipe and key-event tests exercise 640×480, 800×480, 800×390 and 1280×720. Physical PT35 verification is pending. |
| Internal protocol Auto | Synthetic mode-transition tests pass. Detection and dwell timing await a PT35 bench test. |
| Rear WS2812 | Fake driver and socket tests pass. Native Unix socket integration runs where the environment permits it. LED service deployment and physical tests await approval. |
| Internal NFC-A | Implemented single-tag discovery and NTAG213/215/216 user-page reads. Bench check pending. |
| Internal NFC-B | Implemented one-slot ATQB/PUPI discovery. Bench check pending. |
| Internal NFC-F | Implemented one-slot FeliCa polling at 212 kbit/s. Bench check pending. |
| Proxmark3/Iceman HF and LF | Implemented Iceman identification logs and selected structured identifiers. PT35 USB/RF verification pending. |
| Proxmark3/Iceman ISO15693 memory | Implemented addressed raw reads with CRC verification and a 32-block cap per capture. Bench check pending. |
| Proxmark3/Iceman ISO15693 simulation | Experimental, explicit confirmation for a saved verified capture. Bench check pending. |

Offline tests use synthetic frames and temporary archives. Use a graphical display or the virtual desktop below to exercise touch navigation and physical-keyboard event bindings. The Unix socket integration test skips in environments that block AF_UNIX.

```sh
xvfb-run -a -s '-screen 0 1280x720x24' python3 -m unittest discover -s tests -p 'test_nfc*.py' -v
```

### Raspberry Pi bench checklist

Use the same tag, alignment and antenna position in both inventory runs. Stop all other NFC scans first. Repeat with an external known-good Tonie, a generic ISO15693 tag and the onboard ST25DV on its own. Keep other PT35 services running.

**1. Compare inventory with the original scanner.** The baseline is the original `main` scanner from the handoff. The filter below prints counts and discards private UID and frame output. Run this from the PR checkout in Bash.

```bash
(
  set -o pipefail
  baseline="$(mktemp)"
  trap 'rm -f "$baseline"' EXIT
  git show 73751297a6f78e87a4e7d9ecb4e526b7a15510a5:nfc/nfcv_scan.py > "$baseline" || exit
  python3 "$baseline" --count 20 --delay .35 --verbose |
    awk '/^Attempt [0-9]+: no valid tag/{miss++}
         END{printf "Baseline: %d/20 inventory replies (%d missed)\n", 20-miss, miss}'
)

python3 nfc/pt35_nfc.py rf-bench --inventory-only --include-st --tries 20 --delay .35
```

If either command exits with an error, keep the error alongside the count. The comparable counts are the baseline's inventory replies and the new scan's `inventory.ok`. The original and comparison runs both use unmasked inventory and the same NFC-V register profile, 300 ms inventory timeout and high-rate single-subcarrier framing. The new receive path accumulates clear-on-read IRQs. If RX-end is absent, it checks the FIFO within a fixed deadline. Compatibility recovery requires all data and CRC symbols, even when the stream tail was clipped.

**2. Check addressed reads on each tag.** Use this once per tag with a different output filename. The report contains per-stage counts and recent events, including RF register setup, CRC and symbol failures, FIFO/IRQ state, geometry, block retries, tag error codes and RF shutdown. Reports omit UIDs, payloads and raw samples. For a tag that reports reliable geometry, try **All known** separately if full memory is needed.

```sh
python3 nfc/pt35_nfc.py rf-bench --include-st --tries 10 --delay .35 --blocks 8 \
  --diagnostics "$HOME/pt35-rf-addressed.json"
```

Compare `inventory.ok`, `geometry.ok`, `geometry.unknown_geometry`, and the `coverage.*` counts. A verified eight-block range can be complete with the tag's full size still unknown. An ST25DV can return a generic `0x0f` error or withhold some RF replies during I²C activity. Record the error code and timing rather than assuming bus contention from a timeout. See [ST25DV datasheet, section 7.6.3](https://www.st.com/resource/en/datasheet/st25dv16k.pdf).

**3. Check both tags in the field.** Use the GUI in Internal / NFC-V mode. Save the exact onboard UID in Settings and try the external tag with **Include onboard ST25DV** off, then turn it on and try both. The live scanner can try a bounded series of UID masks after a bad unmasked reply or a reply from the configured onboard tag. Each mask is an inventory request. This step needs the physical antenna and both tags present.

**4. Verify Auto, the touchscreen, keyboard and shutdown.** In a terminal on the PT35 desktop, query the active logical size without changing the mode.

```sh
xrandr --current
python3 -c 'import tkinter as tk; r = tk.Tk(); print(f"{r.winfo_screenwidth()}x{r.winfo_screenheight()}"); r.destroy()'
```

Select **Internal** and **Internal protocol → Auto**, then alternate NFC-V, NFC-A and any available B/F tags. Check that each shows its actual protocol and that NFC-V still reads after other modes. At the PT35’s current resolution, tap through settings and type in each field on the built-in keyboard. Check autofocus, Enter, and Esc. Save a theme and settings, exit, and reopen to verify persistence. Start a scan, open a tag, view its memory, save it, search the archive, and export using touch for controls and the built-in keyboard for text. Verify that settings and tag actions are reachable while scanning. Use **Stop scan** and then **Tools → RF diagnostics**. It should show `Last shutdown RF bits: 0x00`. Try several Start/Stop cycles and a five-minute scan with tag removal and re-presentation. Export a redacted report from this screen if any step fails.

For an independent readback with the scanner stopped:

```sh
python3 - <<'PYCODE'
from smbus2 import SMBus, i2c_msg
with SMBus(1) as bus:
    value = i2c_msg.read(0x50, 1)
    bus.i2c_rdwr(i2c_msg.write(0x50, [0x42]), value)
    op = bytes(value)[0]
print(f'ST25R3916 operation control 0x{op:02X}, RF bits 0x{op & 0x48:02X}')
PYCODE
```

Send the per-tag counts, any touch step that fails, and the RF-off result. Keep tag identifiers and contents local. The draft stays open for physical sign-off.

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

**Custom firmware compatibility:** The PT35 now automatically searches `~/proxmark3-iceman/client/proxmark3` as well as the original paths. A responsive hardware ping can connect even when the Iceman client and custom PM3 OS report different Git revisions. The mismatch remains visible as an advisory; it is *not* a requirement to flash the PM3. The application probes ISO15693 read and simulation commands independently; a differing/unknown source revision is advisory and does not by itself disable **PM3 simulation**. Read-only discovery is suitable for a compatibility test; validate raw reads against a known blank tag before relying on them. Test via `python3 nfc/pt35_nfc.py status --backend proxmark3` after closing the interactive Iceman shell, which otherwise owns the serial device.

First identify the exact Iceman revision already on your device, using its working client or your existing firmware records. Build a matching client from that revision and select the platform of the physical device. For example, after substituting your actual release tag or full commit hash:

```sh
bash scripts/install_iceman.sh --platform PM3GENERIC --rev YOUR_FIRMWARE_REVISION --install-deps
python3 nfc/pt35_nfc.py status --backend proxmark3
```

The installer asks before installing packages and builds the userspace client under `~/.local/lib/pt35-iceman`. It performs no device flashing. If you already have a matching client, use **Iceman client path** in Settings, `--client` or `PT35_PM3_CLIENT`. Port selection accepts a detected Proxmark3 device path or its stable `/dev/serial/by-id/` symlink. The app checks recognized PM3 USB IDs or an explicit Proxmark descriptor, serial access, a successful hardware ping, and available emulator commands. A version warning is diagnostic rather than a requirement to rebuild or flash the owner's custom firmware. An unplugged PM3 falls back to the internal reader in Auto mode, and a later responsive PM3 is picked up during a watch.

For plug-and-play diagnosis, compare USB enumeration with the app’s redacted status from the PT35 terminal.

```sh
lsusb
ls -l /dev/ttyACM* /dev/ttyUSB* /dev/serial/by-id 2>/dev/null
id -nG
python3 nfc/pt35_nfc.py status --backend proxmark3
```

The local by-id listing can contain USB serials. Share the app’s status or omit serials from any device listing. If access is denied, check the tty device group and current session’s `dialout` membership. If the Iceman revision differs, obtain the build matching the firmware already on the device before using `scripts/install_iceman.sh --rev ...`.

In **Settings**, select HF, LF or NFC-V as the Proxmark watch mode. Open **Tools → Proxmark3** for device actions. **Identify HF / LF** shows Iceman's logs for both bands. Supported structured rows include NFC-A UID, NFC-B PUPI, NFC-F IDm, NFC-V UID and EM410x ID. Other detected protocols may appear only in the log. B PUPIs can be temporary and may change between sessions.

When the connected firmware advertises ISO15693 raw reads, select a tag and choose **Read selected ISO15693 memory**. This uses addressed, CRC-checked reads. For slower USB polling it limits each operation to 32 blocks. The CLI equivalent is `python3 nfc/pt35_nfc.py pm3-dump UID --save`. Discovery by itself is a metadata capture.

**Multi-reader emulation update:** The Emulation page additionally lists valid saved `EM410X` five-byte LF IDs. Select one for an explicitly confirmed **Proxmark3 `lf em 410x sim --id <ID>`** test, bounded to ten seconds by the Iceman-client timeout and followed by a `hw break` request. On an unresponsive PM3, use its physical button and verify RF is no longer active. It is an **identifier-only** LF emulation, not a memory-card clone. The command is enabled only after the connected client advertises `lf em 410x sim`; it has not been physically tested on the owner's PM3. Proxmark3 ISO15693 and patched SLIX-L continue unchanged.

**Internal M5Stack ST25R3916:** ST confirms the silicon supports NFC-A and NFC-F card emulation, but the PT35's Python `nfcv_scan.Reader` is a polling reader implementation with no target RX/TX state machine or demonstrated target response timing on the current modified I²C module. These capabilities are listed for future bench development, **not enabled or claimed to work**. ST25DV16K itself is a separate built-in NFC-V dynamic tag already presenting user-memory NDEF from the I²C Tag application. NFC-V card emulation isn't a native ST25R3916 target mode.

**NFC-A/NTAG archive constraint:** current PT35 NTAG read captures pages beginning at page 4, not the original UID/manufacturer/lock/configuration pages; NFC-A/F discovery often saves only identifiers. Full-page MIFARE Ultralight/NTAG, Classic, FeliCa and other smartcard emulation requires tag-family-specific verified captures and runtime PM3 firmware support. They are not silently offered as clones from incomplete data.

**New dedicated emulation page:** Open **Tools → PM3 · Emulation** (also linked under Tools → Proxmark3). The GUI reads the existing local archive, lists only validated *complete* ISO15693 captures as selectable tags, explains unsupported/incomplete entries, and offers a separate simulation confirmation screen. It does not emulate generic NFC-A, MIFARE, LF or proprietary tag authentication. Select **Check PM3** while scanning is stopped to query the USB connection and its firmware capabilities. A matching compatible Iceman client is preferred.

**Custom Iceman SLIX emulation:** The PT35 owner's PM3 Easy 512 runs the patched `jenna-slix-r1` firmware for ICODE **SLIX-L** behavior (privacy, random challenge and password-state exchange), not merely stock ISO15693 memory emulation. The client and firmware deliberately have different Git revisions: their version mismatch is an **advisory only**, not a reason to disable `hf 15 sim`. Proxmark3 must respond to a hardware ping and advertise emulator load/simulation commands. Individual `hf 15 eload -h` and `hf 15 sim -h` option text is not a reliable compatibility gate for custom Iceman; the actual emulator-memory upload must succeed and be confirmed before transmitting. The PT35 follows the custom test sequence `hf 15 eload -f pt35-image.json` then `hf 15 sim -t 10000` **without `-u`** (UID comes from the image), with a verified full capture, explicit confirmation and maximum 10-second run. It never flashes the custom firmware. A separate independent-reader hardware test is still needed to verify that the installed custom OS actually executes the patched SLIX-L privacy/password flow. The local capture alone contains user memory/UID, not necessarily hidden password state, and success of the `sim` command does not prove successful Toniebox authentication. For ordinary SLIX vs SLIX-L, confirm actual manufacturer/model and memory geometry; do not silently infer it from the E004 prefix alone.

When the connected firmware advertises ISO15693 emulator load and simulate commands, **Simulate saved ISO15693 tag** requires explicit confirmation and a verified complete capture of 1–128 four-byte blocks. It loads a temporary Iceman image and runs a 10-second simulation. Use a bench tag and an independent reader you are authorized to test. Protected configuration and Tonie authentication are outside the image. Use Stop or the physical PM3 button to abort. RF shutdown and whether the independent reader can read the simulated blocks both require bench verification.

1. In Auto mode start without the PM3, attach it, then unplug and reconnect. Record the transitions and any client/firmware fault. With a forced PM3 backend, check that it waits for the device to return.
2. Try a known HF tag and a known LF tag with **Identify HF / LF**. Use the ISO15693 memory action on a small, blank tag and compare coverage and bytes locally with the internal reader.
3. If the PM3 exposes simulation, use a saved complete capture of that blank tag. Check that the other reader sees it only during the confirmed simulation and that a second run stops on request. Report device platform, firmware revision, operation statuses and any errors, omitting identifiers and tag contents.

Iceman references include the [command catalog](https://github.com/RfidResearchGroup/proxmark3/blob/f90d0d0bf923a5d2c3980e78066ab380e4585c8c/doc/commands.md), [ISO15693 client implementation](https://github.com/RfidResearchGroup/proxmark3/blob/f90d0d0bf923a5d2c3980e78066ab380e4585c8c/client/src/cmdhf15.c), and [client/platform build options](https://github.com/RfidResearchGroup/proxmark3/blob/f90d0d0bf923a5d2c3980e78066ab380e4585c8c/doc/md/Use_of_Proxmark/4_Advanced-compilation-parameters.md).

## Rear NFC LEDs

**Settings → NFC LED effects** starts off. After the compatible LED daemon is deployed, choose **Sweep**, **Pulse**, or **Minimal**, and brightness from 1 to 32 (default 12). The scanner uses the existing service socket and releases its override on Stop or Exit. Lease expiry restores the global mode after an app crash. Existing LED controls still select idle, off, rainbow, color, battery, boot, flash or status. Global off suppresses the NFC override, and temporary battery, boot and flash indications take priority.

**New split-row LED mode (bench verification pending):** In the rear view with the hinge below, the **top eight pixels** (0–7 left to right) show a blue scanning animation, or green *real read progress* computed only from verified blocks/pages and the requested count. Unknown memory size stays indeterminate; a successful read briefly turns the top row green, partial amber, fault red. The **bottom eight pixels** (15–8 left to right) show tag technology with colors: ISO15693/NFC-V blue, NFC-A green, NFC-B amber, NFC-F purple, and PM3 LF red-purple. When the internal ST25R3916 supplies its four-bit AM RSSI register during tag reception, bottom LEDs indicate a **relative peak-held receive strength** (0–8 pixels), not calibrated dBm or distance. If RSSI is absent (including PM3 observations), *only one dim leftmost bottom pixel* indicates the tag type—this must not be mistaken for a strength value. RSSI 0 produces no strength pixels. Do not extrapolate from last tag or from antenna tuning voltage. Scanning resumes on top after result, bottom retains the last tag's indicated type until next scan. All effects are optional and service-fallback safe. This branch's RSSI capture is not yet physically validated on the PT35; compare position changes on a known tag before relying on it. The earlier paired-column progress mapping is superseded by split rows.

### Safe pre-deployment test

This test uses a temporary Unix socket and leaves GPIO12 and the live service alone.

```sh
cd ~/pt35-nfc-bench
python3 -m unittest discover -s tests -p 'test_nfc_led.py' -v
led_ctl status
```

For an optional GUI dry run, start the daemon without hardware on a private socket from the graphical terminal. This is a foreground command.

```sh
python3 services/pt35_led_daemon.py --dry-run --socket "${XDG_RUNTIME_DIR:?}/pt35-led-test.sock"
```

In a second graphical terminal, run `PT35_LED_SOCKET="$XDG_RUNTIME_DIR/pt35-led-test.sock" python3 nfc/pt35_nfc_gui.py` from the bench checkout and enable effects. Stop the dry-run daemon with Ctrl+C.

### Deployment and rollback after owner approval

Use these commands only after approval to replace the live daemon. Run the backup and install from the bench checkout in the same terminal. The existing systemd unit and other PT35 services can stay in place.

```sh
cd ~/pt35-nfc-bench
pt35_led_backup="/usr/local/bin/pt35_led_daemon.py.pre-nfc.$(date +%Y%m%d-%H%M%S)"
sudo cp -a /usr/local/bin/pt35_led_daemon.py "$pt35_led_backup" &&
  sudo install -m 0755 services/pt35_led_daemon.py /usr/local/bin/pt35_led_daemon.py &&
  sudo systemctl restart pt35-leds &&
  led_ctl status
printf 'Backup %s\n' "$pt35_led_backup"
```

With NFC stopped, run `led_ctl nfc-test` and confirm one dim pixel at a time follows the documented path. Run `led_ctl rainbow` and start a scan with effects enabled. Check the blue search animation, paired progress on a larger read, green and amber outcomes, and rainbow returning on Stop, Exit, or within the lease period after a GUI process failure. Turn **NFC LED effects** off while scanning and verify normal LEDs resume. Confirm `led_ctl battery`, `led_ctl boot` and `led_ctl status` still work. Check the PT35 button, fan and Remote Eye services.

To roll back, use the backup path printed above (or assign it to `pt35_led_backup` in a new terminal).

```sh
sudo cp -a "$pt35_led_backup" /usr/local/bin/pt35_led_daemon.py &&
  sudo systemctl restart pt35-leds &&
  led_ctl status
```
