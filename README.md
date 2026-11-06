# PT35 Pocket Terminal

Raspberry Pi 4B-based pocket terminal. This repository is the home for the PT35's device-specific software, services, button mappings, hardware notes, and integrated NFC tooling.

## NFC (work in progress)
- Internal M5Stack ST25R3916 on I2C bus 1, address 0x50; direct 3.3 V supply (board modified to bypass its original regulator); IRQ not connected.
- See the [NFC application guide](docs/NFC.md) for installation, archive behavior and the PT35 hardware checklist.
- Optional Proxmark3/Iceman USB backend is under development.
- Never commit captured RFID/NFC dumps, passwords, hardware secrets, network credentials or private configuration.

## Related projects
- [Collar Pet](https://github.com/DakotaWolfi/collar-pet) — Collar Pet firmware and ST25DV16K mailbox endpoint
- [Vision Pi](https://github.com/DakotaWolfi/vision_pi) — Remote Eye / wireless camera and viewer components

## Migration notes
The current working PT35 was configured manually. Before replacing files or installing services, make a filesystem inventory and preserve a local backup. Test changes in a separate working directory. PT35-specific programs belong here; Collar Pet and Vision code should be copied to their repositories only after comparison with the versions already committed.

The NFC launcher runs from the Git checkout and uses the existing `~/pt35-nfc/archive`.
