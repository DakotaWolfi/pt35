# PT35 NFC — consolidated next-work handoff

**Scope:** Continue existing [draft PR #1](https://github.com/DakotaWolfi/pt35/pull/1) on branch `work/pt35-nfc`. Do not create a new PR or merge. This document consolidates the owner's actual-hardware feedback through 2026-11-07, and supersedes inconsistent earlier UI assumptions. Read `docs/NFC.md`, `docs/WORK_HANDOFF_NFC.md`, `docs/WORK_FEEDBACK_TOUCH_RF.md` and the current code before editing.

## Confirmed hardware and interaction

- PT35 / PocketTerm35 with **built-in physical keyboard**. Touchscreen is for navigation, selecting, scrolling, Start/Stop, Save, browsing—not typing. **No custom on-screen keyboard**, no software QWERTY, numeric pad or symbol pad.
- Physical rear label says **3.5 inch, 640×480** capacitive touch, but owner likely drives a higher *logical desktop resolution* via overscaling to make existing applications fit. **Do not change the OS resolution/scaling.** Query active display mode using actual Pi and make GUI responsive at 640×480, 800×480 and current overscaled mode; favor ~44–48px touch targets when screen density allows, avoid clipping, use scrollable pages and appropriately sized text.
- Recent GUI change to normal `tk.Entry`, automatic focus, Enter confirm/Esc cancel **physically worked** according to owner. Preserve it. Current navy/mint dark theme and persistent Dark/Light toggle should remain; Dark default.
- Internal M5Stack/ST25R3916 connected over `/dev/i2c-1` address `0x50`, polled IRQ, no IRQ GPIO. Existing NFC-V reads remain **unreliable on real tags**: intermittent onboard ST25DV detection, partial memory, and missed external tags. Code's synthetic tests do not validate hardware.
- USB Proxmark3 should be detected, connected and reconnected automatically after plug/unplug; matching Iceman client requirement must be explicit and errors actionable. **No automatic firmware flash**.
- PT35 has **16 WS2812 LEDs** driven by `/usr/local/bin/pt35_led_daemon.py` in existing `pt35-leds.service`, **GPIO12**, accessible through Unix socket `/run/pt35-led.sock`. The deployed daemon source is `services/pt35_led_daemon.py` on `main`. Do not drive GPIO12 from NFC, create a second PixelStrip controller, or restart live service without owner's approval.
- Rear-view photo shows **two horizontal rows of eight** in serpentine order, hinge below:
```
Rear view, normal landscape, hinge below
Top:     0   1   2   3   4   5   6   7
Bottom: 15  14  13  12  11  10   9   8
```
  Wired scan may follow 0→15; column-paired progress from left to right is `(0,15), (1,14), (2,13), (3,12), (4,11), (5,10), (6,9), (7,8)`. Include safe, dim LED index self-test to confirm actual ordering.

## Priority 1 — make NFC-V reliable (blocker)

1. Compare original `main` `nfcv_scan.py` successful paths to current `work/pt35-nfc` receive handling (bounded FIFO fallback when missed IRQ, Manchester CRC checks, RF reset/config, response length classification, collision and timeout classification).
2. Add **privacy-redacted diagnostic counters**: inventory attempts/successes, frames malformed/CRC failures, per-block requested/read/failure, geometry discovery, tag error codes, RF state transitions. Do not publish tag UIDs, dump bytes, auth material or personal data.
3. Test actual Tonie, ordinary/blank NFC-V, onboard ST25DV individually (and avoid built-in tag collision). Restore reliable repeated scans and reads without excessive retries or UI freezes. Actual all-zero 4-byte blocks are valid if RF/CRC/flags/length agree. Never infer full memory from fallback block count.
4. Stop and Close must disable RF; operation-control TX/RX bits `0x48` must clear. Never damage/overwrite existing good captures with later partial ones. Keep finite timeouts.

## Priority 2 — automatic *protocol* detection

Existing `Backend: Auto` only chooses internal reader vs PM3; current internal `protocol_mode` is manually NFC-V, NFC-A, NFC-B or NFC-F. **Add Internal protocol: Auto as default**, with bounded round-robin RF polling of NFC-V/A/B/F, safe reconfiguration and a clear detected technology/status. Once a tag is found, read using its actual protocol capabilities. Keep manual override for debugging. Be accurate: NFC-B/F are currently discovery-only; do not imply memory reading where unsupported. Minimize missed brief tag presentations and collisions. Retest NFC-V after switching. For Proxmark3 implement/describe separate HF vs LF auto-detection limits honestly.

## Priority 3 — Proxmark3 plug-and-play

1. On actual Pi inspect `lsusb`, `/dev/serial/by-id`, ttyACM/ttyUSB device, sysfs product/manufacturer/interface, Iceman client resolution, `hw ping; hw version` and actual device variant. The current `nfc_pm3.py` filters descriptors via `proxmark|pm3` and strict Iceman version parsing; determine **which stage fails**. Do not treat arbitrary serial ports as safe PM3 devices.
2. Auto-select responsive PM3 when connected, use internal NFC backend when absent, and recover on unplug/replug without blocking UI. State clearly: device not found, missing executable client, inaccessible serial port, firmware/client mismatch, connected. User should not need to enter serial port or client path in typical operation.
3. Provide explicit documented installation/setup workflow for matching Iceman userspace client, with user consent for dependency installs, **no firmware flashing**. Preserve optional manual overrides for diagnostics.

## Priority 4 — WS2812 NFC progress/status feature

Integrate via existing `/run/pt35-led.sock` daemon. Existing commands include `idle`, `off`, `rainbow`, `battery`, `boot`, `color r g b`, `flash r g b`, `status`; extend socket protocol in a backwards-compatible way and avoid direct LED hardware access from NFC.

- *Searching* — dim moving blue scan or pulse.
- *Reading memory* — true progress: successfully verified blocks / requested blocks, rendered across 16 LEDs (optionally 8 column pairs, wiring mapping above). If target length unknown, show indeterminate activity instead of invented percentage.
- *Read complete* — short green confirmation.
- *Partial read* — short amber warning.
- *Fault* — short red indication.
- *Stop/Exit/crash* — return to previous/global LED mode and release scanner's temporary priority. Add lease/TTL so a crashed NFC process cannot leave LEDs stuck.
- GUI Settings: **NFC LED effects on/off** (ideally initially off/unobtrusive until the new service is deployed), adjustable dim brightness, scanning animation selection. Persist settings; disabling NFC effects must not switch off unrelated PT35 battery/idle LED behavior.
- Fix concurrency first: daemon currently has multiple animation threads writing to the strip and socket handlers calling hardware concurrently. Ensure one synchronized hardware output owner, non-blocking command handling, bounded rate, no bright full-white flashes by default. Keep battery and boot commands functional, and preserve fan, buttons, Remote Eye, etc.
- Use actual structured NFC worker events for *real* block progress, not pseudo-progress timers. LED socket errors must never interrupt scanning. Include fake LED driver/socket tests and test restore on process failure. **Do not deploy/restart existing live system daemon without user's specific approval**, provide backup/test/rollback procedure.

## Priority 5 — small-screen UX refinements and validation

- Responsive layout based on `winfo_screenwidth()/height()` and actual usable dimensions, not hard-coded 800×480 assumption. Test 640×480, 800×480, 800×390 and detected overscaled display. Avoid overwhelming the 3.5-inch physical screen.
- Keep proven interaction: big touch navigation, scroll/swipe Settings, Archive, Tag Data and Tools; physical keyboard-focused entries; Enter/Esc; light/dark switch with dark default. No mouse or on-screen keyboard required.
- Show currently active reader, protocol, PM3 connection state, NFC read progress and errors clearly; allow Settings/Archive while scanning.
- No blocking calls on Tk UI thread; Start/Stop reliable, handle missing LED service and PM3 elegantly.
- Do not silently migrate, delete or upload archives. Current local `~/pt35-nfc/archive` is private. Public GitHub repo must not contain UID lists, memory dumps, credentials, USB serials or network details.

## Development and acceptance

1. Start with a short implementation plan grounded in current branch; work in small commits **on existing PR #1**. Hardware verification must be distinguished from offline tests.
2. Offline tests: original NFC-V regression/CRC/zero-block/partial overwrite protections, mode switching, PM3 hotplug/no-client/mismatch, LED mock/socket/TTL, layout and keyboard at all target resolutions.
3. Provide easy update command for existing isolated bench checkout:
```sh
cd ~/pt35-nfc-bench
git fetch origin work/pt35-nfc
git switch --detach FETCH_HEAD
```
4. Explicit hardware test checklist: per-tag inventory/read coverage counts (redacted); one-finger settings, physical keyboard; Auto tag switching; PM3 connect/reconnect and status; LED scan/progress/error/return, brightness/off toggle; RF TX/RX `0x00` after Stop; continued PT35 status services.
5. Keep PR **draft** until user confirms operation on the PT35. No new PR, merge or live service overwrite without approval.

Other existing feedback is in PR comments and `docs/WORK_FEEDBACK_TOUCH_RF.md`. This consolidated handoff is the primary scope checklist going forward.
