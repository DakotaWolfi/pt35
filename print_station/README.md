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

## HTTPS and private audit history (40C3 preparation)

**Do not use this kiosk on a shared event Wi-Fi over plain HTTP.** The admin
token and visitor receipt content would otherwise cross that network in
plaintext.

The recommended topology is:

    Browser --HTTPS--> Caddy (:443) --HTTP loopback--> Print Station (127.0.0.1:8767)
                                                    |
                                                    +--> isolated Ethernet printer

There is an example in `Caddyfile.example`. For a publicly trusted certificate,
configure a DNS name, Caddy's certificate issuance, and Internet reachability
for HTTP-01/TLS-ALPN-01 or an appropriate validated DNS-01 challenge. Event
Wi-Fi often blocks inbound traffic, so a DNS name alone does not make this
work. A trusted tunnel to a server you control is another possibility.
Self-signed / `tls internal` certs are **not automatically trusted on visitors'
phones** and should not be used for a public guest-facing page.

Caddy's default reverse_proxy handling ignores untrusted client-provided
X-Forwarded-For headers. Keep Caddy as the single trusted frontend. Do not
configure arbitrary trusted_proxies or expose localhost port 8767 directly.
The Python app uses the forwarded source IP **only** when
`require_https_proxy` is enabled and the connecting peer is loopback.
The web app rate-limits based on this IP (other protective controls are needed
for a public event). The event log also records limited User-Agent metadata.
These are investigative clues, not verified identity, and IPs may be shared.

After Caddy is live and reachable over HTTPS, run from `print_station`:

    bash enable_https_proxy.sh https://YOUR-REAL-HOSTNAME
    sudo systemctl restart fmi-print-station

The script backs up the ignored config to
`config.before-https.json`, then sets `listen=127.0.0.1`,
`access_mode=both`, `require_https_proxy=true`,
`public_base_url=https://...`. This deliberately disables direct
HTTP access to the app from LAN clients. The e-paper's local status check
is permitted over loopback.

Administrator history lives in `print_history.sqlite3`. It includes exact
queued text (no per-print bitmap), structured form fields, timestamps,
queue outcome, source IP, and a bounded User-Agent string. Historical rows
get empty source fields on migration. The admin-only History page has a View
print action and an Edit/Reprint action. Unauthorized attempts to access the
history endpoints are reported to the service journal (without recording
admin tokens).

**Privacy:** Receipt content and IP metadata are personal data. Disclose that
the kiosk stores receipts; protect local backups; establish a retention/deletion
policy. No evidence of visitor identity is guaranteed by an IP address.
The database is compressed, **not encrypted at rest**. Protect filesystem
access and full-disk/backups accordingly.

**Deployment**: Caddy's Debian installer is documented at
https://caddyserver.com/docs/install. Validate config using
`sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile`
before reloading, and confirm the browser shows a valid certificate without
warnings. Set restrictive permissions on the local config and DB.

## Hybrid event network mode: HTTPS administration, HTTP guest printing fallback

The station now supports two separate Python listeners in the same service:

- `0.0.0.0:8767` — **guest HTTP** when `listen=0.0.0.0`: overview, AWOO fines, custom print jobs, status, logo. All administrator API calls return HTTP **403** even if the caller supplies the correct token or spoofs `X-Forwarded-Proto`.
- `127.0.0.1:8768` — **loopback only** for Caddy to reverse-proxy securely via HTTPS. Administrator APIs (history, receipt details, settings, logo changes, printer probe) require both the admin token AND a request to the dedicated admin listener through the HTTPS frontend. Visitor printing also works here.

The web UI hides History and Settings navigation on HTTP connections. This
is cosmetic only; the API checks are the actual security boundary.
Do not enter an admin token on HTTP. The configured HTTPS hostname is for
private administration and preferred guest printing. A trusted public TLS
certificate and valid DNS/network route are prerequisites.

Caddy's example in `Caddyfile.example` proxies **port 8768**, NOT 8767.
Run `bash enable_https_proxy.sh https://YOUR-REAL-HOSTNAME` only when
HTTPS is available. This changes the local config to keep HTTP guest printing
active and HTTPS admin available. It does not publish or provision DNS.
The older HTTPS-only mode (require_https_proxy) remains for backward
compatibility, but should be left false in this hybrid configuration.

**Security trade-off:** HTTP submissions are not confidential or protected
against network modification. Visitors should avoid submitting private
content if they must use HTTP; HTTPS should be preferred whenever possible.
This fallback is for availability, not secrecy. Keep `8768` bound to
127.0.0.1 only, block access to the printer's TCP/9100 from guests, and
continue enforcing job limits. An attacker on the guest network may still
tamper with HTTP print submissions or imitate IPs in some environments.
No administrator access should be attempted using HTTP.

## Custom receipt pictures and reusable templates

The Custom Receipt editor supports PNG/JPEG/WebP uploads as inline **image** items.
The browser flattens transparency to white, converts to 1-bit-looking black and
white, and scales to a maximum **384 × 240 dots**, with **up to 2 images per
receipt**. It sends PNG-encoded data, not raw printer commands. The backend
validates file format, dimensions, image count and encoded size, rasterizes to
ESC/POS GS v 0 bitmaps, and prints elements in editor order. Pillow is
required on the Orange Pi (`sudo apt install python3-pil`).

The audit record stores each receipt's structured fields and embedded
compressed PNG data for later editor reconstruction, not a full-page bitmap.
For receipts containing images, `rendered_text` is a text-only summary
with markers for bitmap blocks. In private History, **Edit / Reprint** loads
images and fields into the custom editor. Note that image processing limits
are deliberately conservative to reduce memory and paper abuse.

The Custom Receipt page has a **My local templates** section: Save, Load,
Delete, Export JSON and Import JSON. Storage is in browser `localStorage`;
it requires no login, admin token, or history access. It is per-browser
and per-origin (HTTP and HTTPS have independent storage). Use JSON export
to move a saved template to a different browser or hostname. Clearing browser
site data deletes local templates; exports can act as backups. Templates
may contain images and private text; exported files and browser profiles
should be handled accordingly. No template is saved to the server just
by pressing Save; **printing still records an audit entry**.

## Device metadata caveat

A normal website cannot reliably obtain visitors' actual OS computer names
or phone names. Print jobs automatically record observed IP and the
browser's supplied User-Agent, which may hint at OS/browser/device model.
These fields are not authenticated identification. The manual device-name
question was removed from guest forms.

## Optional reverse DNS in print audit records

New accepted print jobs enqueue a best-effort reverse DNS (PTR) lookup of the
source IP in one of two daemon lookup workers. A network DNS timeout or missing
PTR entry **never blocks the print request or printer worker**. The audit
database has a migration-safe `reverse_dns` column; existing receipts keep
an empty hostname. The admin History view reports `not available` when
the resolver finds nothing. The job's captured IP and User-Agent remain
available.

Reverse DNS is not a device-name API and is **unverified**: local LAN DNS
might yield `jenna-laptop.lan`, but event Wi-Fi, NAT, proxies or a
misconfigured resolver may yield only a shared gateway/provider hostname, a
spoofable PTR record, or no result. Hostnames and IPs should not be treated as
proof of identity. The guest-facing form does not request a device name.

## Epson TM-T88VI: dynamic link-local address (Avahi DNS-SD)

The directly connected Epson advertises `_printer._tcp` on Ethernet with a stable
mDNS hostname, even when its 169.254.x.x address changes. The print station
can resolve that name for each job and for the admin printer probe.

Example local `config.json` values (keep `printer_port: 9100`):

    "printer_mdns_name": "Printer-79EB5F.local",
    "printer_interface": "enx9cebe8ec46e1"

With these fields set, the old `printer_host` field is *not* used for printing.
The discovery implementation uses `avahi-browse -rtpk _printer._tcp`, checks
the exact advertised hostname, IPv4 link-local address, and specified wired
interface. It deliberately never falls back to the old printer IP on discovery
failure or picks a same-named printer on visitor Wi-Fi. Port 515 in the DNS-SD
advertisement is LPR; the app still uses ESC/POS TCP/9100, so test that port
with `nc -vz 169.254.235.98 9100` first.

Requirements: `sudo apt install avahi-utils avahi-daemon`. These are already
installed on the current Orange Pi. The HTTPS admin settings page also exposes
printer discovery hostname and wired interface. After updating the local
ignored config, restart the web service. Do not assign a static IP to the Epson.

## Detailed AWOO Fine ticket layout

The AWOO Fine page uses the longer receipt format: AWOO FINE title, a five-digit ticket number derived from the persisted SQLite job ID, the actual issue timestamp with local timezone offset, offender, issuer, location, offence, officer notes, fine amount, UNPAID status and parody footer. The top header logo remains controlled independently by the admin logo setting. The compact ticket style is not used for AWOO Fines. The UI preview shows a ticket-number and timestamp placeholder until printing. The completed structured audit record contains the final printed text, assigned ticket number and issue timestamp. No custom receipt changes.

## Custom Fine

A separate **Custom Fine** page keeps the detailed numbered fine receipt layout while allowing a visitor to customize the ticket heading, status, offence, offender, issuer, notes, amount, currency and location. It submits to the existing protected/rate-limited `/api/print` endpoint as a normal `fine` audit entry with `custom_fine=true`. The SQLite job ID supplies its ticket number; the parody legal disclaimer remains fixed. The in-browser preview approximates the printout before the number/time are assigned. Private History → Edit / Reprint opens custom fine entries in the Custom Fine editor, not the normal AWOO form. The custom free-form receipt designer remains separate.

## Isolated printer DHCP (optional)

An **opt-in** script `setup_printer_dhcp.sh` configures the Orange Pi as a
DHCP server **only** on USB Ethernet interface `enx9cebe8ec46e1`, not a
router. It adds Pi address `10.88.77.1/24` and offers Epson DHCP leases in
`10.88.77.20-10.88.77.40` using dnsmasq, with no gateway or DNS option,
no IP forwarding, bridging or NAT. It leaves `wlan0` unchanged. Running
without `--apply` is a dry-run description; activation requires root and
`--apply`. The printer must be in DHCP/Auto IP mode and restarted to request
a lease. On this printer, dynamic Epson discovery on Ethernet prefers any
new `10.88.77.x` address over stale `169.254.x.x` link-local addresses.
Check `ip -br addr`, `sudo journalctl -u dnsmasq -n 60` and
`avahi-browse -rtp _printer._tcp` after enabling. This script is written
for **this** Pi's interface name; review before use on a different host.

## e-paper QR and ST25DV16K tap-to-open (opt-in tag writing)

Install `sudo apt install python3-qrcode python3-smbus2 i2c-tools`.
The e-paper status service obtains the current `wlan0` IPv4 address and
displays its **guest HTTP** link as a QR code; `nfc_url` in `config.json`
overrides the automatically detected URL if set. A public HTTPS admin URL
must never be stored in a guest-facing tag. If QR generation is unavailable,
the display falls back to its original printer status screen.

Tag writing is disabled by default. To identify the ST25DV16K I2C bus:
`ls /dev/i2c-*` then inspect the bus using `sudo i2cdetect -y BUS`.
The ST25DV16K's user-memory interface is normally at address `0x53`,
system memory at `0x57`; other I2C devices can be present, so verify the
bus and tag before writing. The conservative `nfc_tag.py` program refuses
unformatted/non-NDEF tags and unknown TLV layouts, reads the existing data,
and shows a dry-run unless `--write` is supplied. On write, it saves an
owner-only backup of the original memory to `/tmp` and verifies readback.
Example after selecting the correct BUS:

    sudo python3 nfc_tag.py --bus BUS --url http://192.168.200.7:8767/
    sudo python3 nfc_tag.py --bus BUS --url http://192.168.200.7:8767/ --write

After a successful manual write and phone tap test, set
`"nfc_i2c_bus": BUS, "nfc_auto_update": true` in config.json and restart
`fmi-print-display.service`. The display service will only reprogram when
the URL differs, minimizing EEPROM wear. The QR and tag then share the same
guest HTTP address, even as wlan0 changes IP.

## Print Pet and physical-presence challenge (optional)

The e-paper layout shows actual Collar Pet wolf expression PNGs, happy/sad/printing
mood, basic printer/queue state, a QR for the current guest HTTP page, and
(if enabled) a six-digit print code. It is a lightweight display concept,
**not** a port of the full Collar Pet runtime. Install the artwork once with
`bash fetch_collarpet_assets.sh`; it pulls only `pi/assets/wolves` from
`DakotaWolfi/collar-pet` using a shallow sparse Git checkout and copies the
`wolf_*.png` assets to the local `print_station/assets/wolves` directory.
The display maps READY to `wolf_happy.png`, PRINTING to `wolf_startled.png`,
and OFFLINE to `wolf_annoyed.png`, with `wolf_idle.png` as fallback.
The e-paper refresh interval is usually 90 seconds, so transient printing
can be too brief to catch visually. LEDs would need their own controller.

Enable the challenge locally (config.json is private and not tracked):

```bash
cd ~/pt35/print_station
python3 - <<'PY'
import json
from pathlib import Path
p=Path("config.json")
data=json.loads(p.read_text())
data["challenge_enabled"]=True
p.write_text(json.dumps(data,indent=2)+chr(10))
PY
sudo systemctl restart fmi-print-station fmi-print-display
```

On first startup the service creates a random, owner-only key in
`/home/jenna/.local/state/fmi-print-station/challenge.key` (mode 0600).
Do not copy it into Git. The six-digit code changes every 10 minutes, and
the prior code is accepted for e-paper refresh lag. The server validates
the code on **all** guest printing endpoints (`/api/print`, `/api/custom`).
If key access fails, guest printing fails closed. Turning the challenge
off requires an explicit private config change and service restart.

For a short-lived owner pass, open the admin HTTPS Settings page, enter the
admin token and press **Get temporary print pass**. The resulting 10-character
pass and QR can be shared with a trusted visitor. Scanning the QR opens the\nguest page with the pass prefilled via a URL fragment (not an admin URL).\nIt is a **printing-only**
bypass, NOT an admin token, and works for at most 10 minutes. It does not
bypass rate or queue limits. The pass is issued only via an authenticated
HTTPS admin endpoint; unauthenticated guests cannot request it.

This challenge mitigates casual remote abuse; it is not strong user
authentication. A visitor can photograph or share a visible code.

## I2C/NFC bus discovery

Run `sudo python3 scan_i2c_buses.py` to enumerate all I2C controllers and
probe the ST25DV16K user/system addresses (`0x53` and `0x57`) separately
with three-second subprocess timeouts. It displays each bus's controller path
and skips HDMI/DDC controllers by default. `--full` probes the broader
0x08-0x77 address range and is **not** recommended on unstable buses; this
can trigger bus errors and interfere with existing peripherals. The scanner
performs SMBus read-byte probes, not EEPROM writes. An acknowledgement at
0x53/0x57 does not prove the chip is an ST25DV16K. On this Orange Pi,
bus 9 corresponds to `0x2519000.twi` and previously logged SCL timeouts;
bus 20 is HDMI/DDC.

## ST25DV setup on Orange Pi bus 0 and Epson DHCP lease diagnostics

After fixing the bus-0 SDA connection and enabling I2C, the tag responds at
0x53 and 0x57; the user's additional 0x2D address belongs to their NFC board
setup and is not an unrelated mystery device. The integration deliberately
writes only ST25DV user memory at 0x53.

For an initial read-only NDEF preview (no tag or config edits):

```bash
cd ~/pt35/print_station
sudo python3 setup_nfc_guest.py --bus 0
```

If the CC/TLV and existing data are recognized, run
`sudo python3 setup_nfc_guest.py --bus 0 --apply` to write the current guest
Wi-Fi URL, verify read-back, and enable NFC auto-updates in private
`config.json`. Restart `fmi-print-display`. Do not enable writes if the
read-only preview rejects the CC layout or bus communication is unstable.

The app now prefers the **current dnsmasq lease** assigned to the expected
Epson MAC `f8:25:51:79:eb:5f` on `10.88.77.0/24`, instead of trusting a
stale `printer_host` value. The guest Overview shows
`Epson DHCP: <IP>` when the lease file can be read. The lease normally lives
at `/var/lib/misc/dnsmasq.leases`. Run:

```bash
sudo journalctl -u dnsmasq -n 40 --no-pager
sudo cat /var/lib/misc/dnsmasq.leases
ls -l /var/lib/misc/dnsmasq.leases
ip -4 addr show dev enx9cebe8ec46e1
nc -vz 10.88.77.30 9100
```

If the lease is at a different path or unreadable by the Print Station
service user, app detection falls back to mDNS when configured.
`setup_printer_dhcp.sh --apply` reserves `10.88.77.30` for that MAC,
but **the Epson must renew DHCP** (usually via printer restart) to move from
an earlier lease such as `10.88.77.39`.

## PT35 ↔ Print Pet offline NFC mailbox (experimental; opt-in)

Hardware: Print Pet ST25DV16K on I2C bus 0, with GPO wired to PB4
(physical pin 7, gpiochip0 line 36); PT35 internal ST25R3916 NFC-V
reader on I2C bus 1. Link uses ISO15693 RF, **not Wi-Fi**.

On Print Pet: run `sudo python3 mailbox_inspect.py --bus 0` to read
static MB_MODE, dynamic MB_CTRL, and GPO (read-only). If MB_MODE is disabled,
the protected static mailbox mode must be enabled using an authorized I2C
security session; neither diagnostic nor host guesses passwords or modifies
protected registers. If MB_MODE is enabled, set `challenge_enabled: true`
in local `config.json`, restart `fmi-print-station`, then manually run
`sudo python3 mailbox_host.py --bus 0`. The host only enables dynamic FTM,
reads/writes 256-byte RAM mailbox, and forwards validated requests through
the existing local print HTTP API. Do not enable automatic boot yet.

On PT35: use the existing `nfc/nfcv_scan.py` to locate the **external**
Print Pet tag UID; the PT35 has its own ST25DV tag in RF range.
Run from the `nfc/` directory:

```bash
python3 print_pet_mailbox.py status --uid EXTERNAL_ST25DV_UID
python3 print_pet_mailbox.py print --uid EXTERNAL_ST25DV_UID --name PT35 --message AWOO --code 123456 --confirm
```

Substitute the real six-digit code shown on the Print Pet e-paper.
Hold PT35 close to Print Pet throughout the exchange; an NFC field can
drop mid-request. The PT35 ST25R3916 backend is shared with its existing
NFC scanner, so stop the scanner/GUI before running the mailbox client.

Protocol: `print_station/mailbox_protocol.py` defines bounded FMP1 JSON
messages, with eight-hex-character request IDs and a 112-byte application frame limit. `mailbox_host.py` handles
I2C side; `nfc/print_pet_mailbox.py` RF side. Every print call still uses
normal application challenge/rate limits/audit records. A random ID is
deduplicated for 90 seconds in daemon RAM; this is **not cryptographic
authentication or durable exactly-once printing**. NFC proximity and UID
are not credentials. No raw ESC/POS bytes or secrets may be sent.

**Not yet hardware validated end-to-end.** RF command framing, mailbox
half-duplex handoff and ST25R3916 large response decoding must be checked
with both physical devices before calling the feature working.

### One-time MB_MODE activation

For an owned ST25DV16K whose MB_MODE is 0, `sudo python3 mailbox_enable.py --bus 0`
previews the change, while `sudo python3 mailbox_enable.py --bus 0 --apply`
presents the ST-documented eight-zero-byte **factory** I2C password (without
changing that password), checks I2C_SSO_Dyn, sets **only** bit 0 of static
MB_MODE at system I2C address 0x57 / offset 0x000D, and verifies readback.
It preserves the existing GPO configuration and NDEF URL. It refuses to
write MB_MODE if the factory password fails. This is a one-time persistent
configuration change, not a recurring service operation. See ST AN4910.

### Print Pet picture GUI and original PT35 R menu

PT35 can stage the independent graphical app without changing its R launcher:
`bash ~/pt35/scripts/install_print_pet_gui.sh` after fetching
`nfc/print_pet_gui.py`, `nfc/print_pet_mailbox.py`,
`print_station/mailbox_protocol.py`, and the install script from the
feature branch. Launch with `~/.local/bin/pt35-print-pet`.

The 800x480 GUI has Status, Text receipt and Picture tabs. Image prints
are compressed to a monochrome 160x120 PNG (<=7680 bytes) and sent as
30-byte binary chunks encoded in FMP1 messages. The host stages <=8192
bytes, checks a truncated SHA-256 identifier, verifies the PNG and then
calls the local /api/custom endpoint through the paired owner bridge.
This pathway is **experimental and not yet hardware tested**. Moving the
antennas mid-transfer can fail the operation; a lost final acknowledgement
means the sender must not auto-retry printing.

The PT35 R button runs `~/.local/bin/pt35-nfc-menu` -> `pt35-launcher`,
which starts `~/pt35-nfc-bench/tools/pt35_launcher.py`. Its canonical
source is the `work/pt35-nfc` branch, and the updated launcher is also
present in `feature/fmi-print-station`. The six tiles now replace LED Test
with Print Pet, replace LRA Test with Diagnostics, and retain the original
LED and LRA test pages underneath Diagnostics. The standalone GUI installer
intentionally does not touch the launcher wrappers.

### One-shot PT35 owner pairing (SSH arm + encrypted NFC transfer)

The six-digit web visitor challenge is **not required over NFC**. Pairing is
disabled by default, and can only be armed locally on Print Pet from a trusted
SSH session. Arming creates a fresh 32-byte owner secret and a maximum
90-second window, without replacing the currently active key yet. PT35 uses
an ephemeral X25519 key pair to encrypt the secret transfer under AES-GCM.
NFC pairing requires three RF exchanges: ephemeral public-key exchange,
encrypted secret retrieval, and a keyed `pair-done` confirmation. After
confirmation Print Pet activates the new key and removes the armed state.
PT35 persists its key to `~/.config/pt35/print_pet.key` (0600). Existing
pairings are rotated when a new pairing completes. The Print Pet key is in
`print_station/.private/nfc_pairing.key` (0600), and is ignored by Git.

Install dependencies on **both** devices (the Print Pet also needs Pillow
for e-paper and PNG printing):

```bash
sudo apt update
sudo apt install -y python3-cryptography python3-smbus2 python3-pil python3-pil.imagetk python3-tk
```

On **Print Pet** as the normal owner (no sudo), prepare the owner-readable
private directory and start the updated API and NFC mailbox host:

```bash
cd ~/pt35
git pull --ff-only
install -d -m 700 ~/pt35/print_station/.private
sudo systemctl restart fmi-print-station fmi-print-display
cd ~/pt35/print_station
sudo /usr/bin/python3 mailbox_host.py --bus 0
```

If another mailbox host is already running, stop it first rather than
starting two processes. Keep the host running in a separate terminal.
On Print Pet **over SSH**, arm a single pairing window:

```bash
cd ~/pt35/print_station
/usr/bin/python3 nfc_pairing.py arm --seconds 90
```

On **PT35**, after fetching the updated GUI, NFC client, protocol and
authentication module, select `R > Print Pet > Status > Pair owner key`.
Hold the devices' NFC antennas aligned until confirmation finishes.
The key transfer uses encrypted RF frames. Pairing is then automatically
disarmed; no one can pair another device without rearming via SSH.
An uncompleted session expires after the SSH-configured timeout.
Check `python3 nfc_pairing.py status` on Print Pet.

After pairing, **owner NFC text/picture prints** send a short time-windowed
HMAC. The HTTP application accepts the owner request only from loopback
with the exact owner key, bypassing the six-digit **web** challenge, guest
hourly quota and guest cooldown; the finite printer queue and input
validation remain enforced. Owner print request replay responses are cached
persistently for five minutes in the private directory. Keep PT35 and
Print Pet clocks synchronized. Status reads remain public.

The NFC pairing exchange encrypts the owner key against passive radio
observation. It is not a fully authenticated MITM-proof PAKE: an active
adversary present during the short SSH-armed window could interfere with
pairing, and key extraction from an unlocked PT35 is not prevented. Do not
leave pairing armed unattended. Printing over NFC and large picture transfers
still need end-to-end hardware verification.

### Monochrome Print Pet e-paper screen

`display_epaper.py` now draws a landscape **250x122 monochrome** layout,
preserving the real wolf mood bitmap on the left, queue/printer/NFC pairing
state in the center, and the guest QR on the right with **WEB CODE**
directly beneath it. The header also shows READY/PRINTING/OFFLINE and
Q/P counts. When the web visitor challenge is disabled, the reserved code
region shows OFF. To enable six-digit visitor codes (while NFC owner prints
remain code-free), in `print_station/config.json` set:

```json
"challenge_enabled": true
```

Restart the printer API and e-paper service, and preview without writing
to the physical display using:

```bash
cd ~/pt35/print_station
/usr/bin/python3 display_epaper.py --preview
```

The preview is saved at `/tmp/fmi-print-display.png`. The actual
monochrome screen updates with `sudo systemctl restart fmi-print-display`
and normal service refreshes. QR density can constrain scanability on
the very small 68-pixel square; use a short guest URL.

To install the optional **boot-start NFC mailbox service** (stop any
manually launched mailbox_host.py instance first):

```bash
cd ~/pt35
sudo install -m 0644 print_station/fmi-print-nfc.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now fmi-print-nfc
sudo systemctl status fmi-print-nfc --no-pager
```

Do not run two mailbox host processes on the same I2C bus.

### Diagnose PT35 to Print Pet NFC antenna alignment

The PT35 Print Pet Status tab now has **NFC link quality / positioning test**.
It sends 40 read-only status mailbox requests, shows per-transaction RTT,
last-10 success percentage, total success rate and effective application
payload bytes per second. A perfect 10/10 moving window is 100%.
These numbers measure end-to-end mailbox reliability, **not calibrated RF
SNR or ST25R3916 RSSI**, and should be interpreted accordingly.

CLI alternative on PT35:

```bash
cd ~/pt35
/usr/bin/python3 nfc/print_pet_mailbox.py linktest --uid E00226003269825F --samples 40
```

Position the two NFC antennas differently between runs and compare total
success rate and RTT. Do not run the test at the same time as printing or
scanning from another PT35 program. Link testing **does not print**.

Image printing retries *data and start* chunks up to three times with the
same request ID, and attempts to recover a previously written mailbox
response; the final print-commit chunk is never automatically resent.
If full pictures are still unreliable, prefer NFC for authenticated
handshake/short commands and an independently authenticated Bluetooth or
Wi-Fi link for large binary transfers.

### Print Pet reactive e-paper and matching dark PT35 touch UI

The 250x122 **monochrome** display shows **READY/OFFLINE/PRINT** and
queue/printed counters **only once in the header**. The left side is the
wolf expression/mood, and the center is a context-sensitive pet message
plus NFC state. The redundant second READY, second Q/P and PRINTER OK
labels were removed. The right side remains guest QR + WEB CODE (or OFF
when the guest challenge is disabled).

The pet reacts to actual local events recorded by the two services;
`pet_activity.py` writes only timestamps, no tag UID, visitor names,
message contents, or secrets:

- NFC read/status or alignment test -> curious wolf / NFC HELLO!
- SSH-armed owner pairing -> listening wolf / PAIRING
- Web page request -> social wolf / WEB VISITOR
- Web/NFC receipt queued -> startled wolf / corresponding receipt message
- Printer starts work -> startled wolf / PRINTING!
- Printed successfully -> smug wolf / GOOD JOB!
- Print failure -> annoyed wolf / PRINT ERROR
- No recent activity -> happy wolf / AWOO :3

The real wolf PNGs come from `fetch_collarpet_assets.sh`; re-run it if
`wolf_smug.png`, `wolf_social.png` or `wolf_listening.png` is absent.
Events expire and automatically return to idle. The display checks for
changes every 5 seconds but limits full-panel refreshes to **at most one
per 25 seconds** (configurable via `display.activity_min_refresh_seconds`;
minimum 20 seconds). Existing periodic refresh stays at >=60 seconds.
This is deliberate for e-paper: fast animated expressions are not possible.

The PT35 Print Pet Tk interface now follows the installed PT35
`nfc_touch` dark colors: navy backgrounds, mint accent buttons,
larger touch targets, and a live NFC quality bar. PgUp/PgDn and Ctrl+Tab
switch between Status, Text, and Picture. To update PT35 client scripts,
fetch `feature/fmi-print-station` and restore
`nfc/print_pet_gui.py`, `nfc/print_pet_mailbox.py`, and matching
`print_station/mailbox_protocol.py`. Printer service and display Python
sources must instead be updated on the **Print Pet Orange Pi**.

On Print Pet, ensure `~/pt35/print_station/.private` is accessible
to the `jenna` HTTP service user (typically mode 0700, owner jenna).
Restart `fmi-print-station`, `fmi-print-display`, and (if installed)
`fmi-print-nfc` after updating. To preview the actual renderer:
`/usr/bin/python3 display_epaper.py --preview`.

### Large source photos in the web custom receipt form

The Custom Receipt image upload now sends the **original** selected image
to `POST /api/image/prepare` as a bounded binary upload. Print Pet uses
Pillow to apply EXIF orientation, respect transparency, downsample to fit
**384x240**, grayscale/autocontrast and monochrome Floyd-Steinberg dither,
then returns an optimized **1-bit PNG**. The browser previews this compact
PNG and submits only that result in the existing custom receipt. The original
photo is **not saved in print history**.

Inputs supported: JPEG, PNG, WebP, GIF, BMP, TIFF. Limits: **12 MiB
compressed source and 32 megapixels decoded**, at most two images per
receipt. Source images above those limits are rejected with a clear message;
image conversion is capped at two concurrent jobs and eight per
source IP per minute. This web-only conversion depends on Pillow installed
in the Print Station server environment. It does not relax the NFC
112-byte mailbox payload limit.

PT35 NFC Picture now adaptively shrinks a large source image, targeting
**850 bytes** of 1-bit PNG data to reduce the number of RF exchanges.
Print Pet then uses Pillow to enlarge the received thumbnail (aspect
ratio retained; maximum 384x240) for the Epson raster command. This is
a practical compromise for the currently unreliable NFC RF channel;
very fine photographic detail may be lost, especially for complex photos.
For the best image quality use the web upload or a future Bluetooth/Wi-Fi
bulk transport.
