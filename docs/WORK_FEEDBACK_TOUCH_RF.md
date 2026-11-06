# Hardware feedback: Phase 1 not accepted — read reliability + touchscreen overhaul

Observed on actual PT35 with draft PR #1 (`work/pt35-nfc`):
- **Internal NFC-V reads are more miss than hit**. Onboard I2C ST25DV sometimes detects but provides only partial reads; ordinary NFC-V tags are also unreliable.
- **Current GUI is not usable on the small PT35 touch display**: Settings are effectively inaccessible and controls are not touch friendly. An 800×480 screenshot test passing is insufficient.
- Do not merge PR #1 or call these capabilities tested until real-hardware verification succeeds.

## Blocker A — debug NFC-V first
1. Instrument each stage separately: RF configuration, inventory, addressed System Information, each block transaction, CRC/symbol checks, timeout, tag error, FIFO/IRQ state, and RF shutdown. Record error class and block index without recording UID/content by default. Include on-demand diagnostic log export with sensitive IDs redacted.
2. Reproduce on **one external known-good Tonie**, **one generic ISO15693**, and **onboard ST25DV** (explicit inclusion); isolate collision problems when the onboard tag and external tags are simultaneously in field. Verify scanner frequency/timing/poll resets against baseline `nfc/nfcv_scan.py` known working capture.
3. Compare original `main` scanner and Work branch with same tag and alignment. Avoid blanket retry inflation; recover chip/FIFO state after malformed/partial frames, finite retry budget, no scan freeze.
4. Never mark a partial fallback range as full tag memory; preserve valid all-zero blocks; never overwrite a higher-quality archive.
5. Acceptance: repeated runs on each test tag with counts of complete inventory/geometry/memory reads, sustained Start/Stop and RF off, no regression in original scanner. User signs off on reliability before merging.

## Blocker B — rebuild the GUI for the small display

The PT35 has a built-in physical keyboard. Use touch for navigation, buttons, scrolling and selections, and the physical keyboard for typing.

The original `nfc/pt35_nfc_gui.py` used `ttk.Notebook` (five narrow tabs), a multi-column Treeview, tiny comboboxes and checkbuttons, keyboard-oriented text entries and a cramped grid. Replace rather than adjusting a few widget margins.

- Design for **800×480 landscape as the primary target** (confirm actual resolution on PT35), with **minimum ~44–48 px effective touch targets**, generous spacing, large legible type, high-contrast readable status, and no horizontal clipping.
- **Full-screen-friendly home/scan view:** one large Start/Stop control, clear active backend/protocol, detection status, newest tag summary, and two or three large navigation actions; avoid showing large raw logs permanently.
- **Dedicated scrollable Settings screen** with large select/option controls and explicit Save/Back actions always reachable by finger; vertical scrolling with a visible scrollbar and swipe-compatible scroll. For backend and protocol use large tap selections instead of tiny comboboxes. Provide large block-count presets (Auto / 8 / 32 / All known) and a focused text field for custom values.
- **Tag detail screen** with readable summary/coverage and prominent Save/Export; separate horizontally paginated or vertically scrolling hex view that doesn't take over screen.
- **Archive screen** with large single-column tappable cards and search/filter using a focused physical-keyboard field. PM3 actions on their own screen with safe confirmations and operation state.
- Layout must adapt to 800×480 and smaller usable height (taskbars/title bars), and the GUI must support touch navigation and built-in keyboard input. Text editors focus automatically, with Enter to confirm and Esc to cancel. Provide an explicit Back/Home button and a close/exit control that is reachable.
- Favor robust simple Tk widgets or an alternative UI stack already installed on Pi; don't add a heavy dependency without demonstrating performance on Pi. No log spam on main page; diagnostics secondary.
- Settings changes should persist and apply to the next scan, and touch navigation should not require stopping a worker.
- No concurrent RF worker, no UI-thread I/O, bounded queue, cleanup on Stop/Close.

## Touch and hardware acceptance checklist
- On the physical display, reach every option by touch and edit text with the built-in keyboard. Save, exit, reopen and verify persistence.
- Switch Auto/Internal/PM3 and NFC-V/A/B/F by touch.
- Use touch to start and stop scanning, select a tag, show raw content, manually save and export. Open archive search by touch and type on the built-in keyboard.
- No clipped options/buttons at 800×480 with actual title bar/taskbar; GUI stable under 5+ minutes of scanning and malformed reads.
- Report per-tag coverage and errors without disclosing UID/data publicly, verify operation-control RF bits `0x00` after Stop.
- If app can't meet this, keep PR draft and present blockers honestly.

**Suggested development order:** baseline comparative RF instrumentation -> reproduce and repair NFC-V -> touch-first GUI redesign -> offline UI tests -> request live PT35 verification. Keep live archive and other services unchanged.