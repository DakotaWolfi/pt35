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
