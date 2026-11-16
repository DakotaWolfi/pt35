# FMI Print Station (experimental)

A standalone, cross-device Python receipt printer kiosk inside the PT35 repository.
Runs on PT35, Raspberry Pi 4B, Raspberry Pi 1 with supported Python, or a development PC.
**Does not change existing PT35 services or install automatically.**

## Quick start

Requires Python 3.9+; uses only the standard library.

\`\`\`bash
cd print_station
cp config.example.json config.json
python3 app.py
\`\`\`

Browse http://127.0.0.1:8767. Default **dry_run=true**: no paper consumed.
To print, set \`printer_host\` to the Ethernet Epson's reachable IP, set \`dry_run=false\`, and restart.
The printer is accessed using ESC/POS over TCP/9100. Paper feeds 50 mm before optional partial cut by default (`feed_mm`: 50).

## Modes / hosting

- \`access_mode=local\` (default): accepts clients from \`local_networks\`. Set \`listen=0.0.0.0\` to serve your LAN (configure the firewall).
- \`access_mode=public\`: requires \`public_base_url=https://...\`, still requires independently configured **TLS reverse proxy/tunnel**. **It does not publish your server automatically**.
- \`access_mode=both\`: both local access and a public reverse-proxied entry point.
- Use \`nfc_url\` as the URL you intend to program into a passive NFC tag or update on ST25DV16K over I²C. NFC writes/e-paper hardware integration are future work.
- Suggested public website setup: a landing page at \`https://famosindustries.ch/print\` which links or redirects to an HTTPS print-station service. The public website by itself cannot reach a Pi behind NAT; you must provide a reverse proxy/tunnel or backend relay.
- When behind a reverse proxy the app sees the proxy's IP and its per-IP quota is **not a reliable per-visitor limit**. Enforce visitor limits and HTTPS at the trusted proxy too. Do not blindly trust visitor-controlled \`X-Forwarded-For\`.

## Safety and limitations

This is a **prototype, not ready to publish openly on the internet**. Rate limiting is in-memory, restarts clear it; browsers can share IPs, and botnets can evade per-IP limits. The default print API supports only short ASCII messages, serializes jobs, and does not accept raw ESC/POS or images. Keep the printer's TCP/9100 port on an isolated Pi↔printer wired subnet. No IP forwarding required. Consider operator approval, daily page limits, authenticated access, captcha, persistent quota, and a proper job log before public use. User inputs do not receive direct printer commands. No special privileges required. Do not expose administration endpoints or configuration files. Use a separate identity for local admin tools.

The Raspberry Pi's Wi-Fi interface serves visitors; the Pi Ethernet talks to the Epson on a private subnet, e.g. Pi eth0 192.168.50.1/24, Epson 192.168.50.2/24. The wifi network must permit access to the Pi, or visitors need to use the public HTTPS route.

### Configurable external hardware (planned, not implemented)
Display selection (2.9" SPI e-paper on Pi 4B; SSD1306 I²C OLED on Pi 1).
NFC selection (static NTAG URL; ST25DV16K dynamic I²C tag).
Power: use separately rated 5.1 V supply or verify buck/24 V printer PSU margin under load.

## Testing

\`\`\`bash
python3 -m unittest discover -s tests
\`\`\`

Do not put secrets in config.json or commit it. The global PT35 .gitignore might not ignore this file, so keep credentials in environment files stored outside Git.


## v0.3 — AWOO Fine Office-inspired interface

Dark blue/cyan styling, live receipt preview, optional logo image (PNG/JPEG/WebP),
expanded fine fields and administrator-controlled printer/receipt settings.
Install `sudo apt install python3-pil` for image printing.
To unlock settings and image uploads from the browser, configure a long random
`admin_token` in the private, untracked `config.json`. Enter it in the
page's Admin token field. Do not publish the token or expose this prototype on
an untrusted network. Printer settings update immediately and persist on disk.
The ticket print endpoint remains subject to the existing cooldown and limits.
The displayed preview is approximate, and the ticket history remains future work.


## Multi-page web interface and compact receipt history

The web interface now provides Overview, AWOO Fines, Custom Receipt, Print History and Settings (hash navigation in one HTML document).
Custom receipts support up to 25 structured blocks: text, heading, label/value, divider and blank line.
The live preview approximates the printer output. No raw ESC/POS commands are accepted from the web browser.

Every submitted receipt is stored in local \`print_history.sqlite3\`, using SQLite with zlib-compressed JSON containing its form fields, exact queued ASCII text, and selected print settings. SQLite records the time and final \`queued\` / \`printed\` / \`failed\` outcome. This database stays on the machine and is ignored by Git. It survives process restarts but is **not** mirrored to GitHub. Include it in your local backups. The history page requires the administrator token and can load saved fields into the editors. Reprinting creates a new record.

History is *not* an image archive: existing uploaded logo images are not versioned or retained per job, and ESC/POS printer output (font metrics, cutting, and physical printing) cannot be guaranteed to reconstruct byte-for-byte from these records. The text of the receipt is retained.

The update timer automatically fetches changes on the feature branch every 30 minutes and refuses updates on a dirty tracked working tree. Follow service logs after deploying changes.
