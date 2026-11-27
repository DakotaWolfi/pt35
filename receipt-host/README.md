# PT35 Receipt Host — v0.1

Portable receipt composer/server for a Raspberry Pi 5 running the PT35 software. It **does not** modify any other PT35 services.

## Features
- Touch/keyboard-friendly browser UI at `http://127.0.0.1:8765`
- Print heading, body and optional photo, rendered as monochrome PNG
- Sends jobs through **CUPS** so USB, serial, parallel and network printer queues can be supported according to their Linux drivers
- Shows recent job submissions (memory only; not a physical-print confirmation)
- Defaults to **localhost only**. Optional password-protected access on your trusted Wi-Fi LAN

## Install on PT35 / Pi 5 (Debian)

```bash
git clone https://github.com/DakotaWolfi/pt35.git
cd pt35/receipt-host
sudo bash install.sh
lpstat -e
```

Until merged to main, clone the feature branch using `git clone -b feature/receipt-host-v0.1 https://github.com/DakotaWolfi/pt35.git`.

Add your printer to CUPS first. Exact steps depend on **which** Epson TM model and whether it uses USB, serial, parallel, or Ethernet. Inspect `lsusb`, `lpinfo -v`, `lpstat -t`. For the CUPS administration site, `http://localhost:631` and a compatible driver/filter are often needed. Some ESC/POS printers need a dedicated raster filter rather than a generic text driver; verify with a small test receipt.

## Direct Ethernet printer: opt-in DHCP server

The PT35 can provide addresses to DHCP clients directly connected to its Ethernet port. The feature uses NetworkManager's per-connection `ipv4.method=shared`, rather than leaving an always-on DHCP daemon running. It needs active NetworkManager and `dnsmasq-base`; the installer does not change an alternative network management stack.

**Off by default**, on every boot. The dedicated connection profile `PT35 Printer Ethernet` has autoconnect disabled.

- PT35 Ethernet interface: `eth0`
- PT35's Ethernet address when enabled: `192.168.77.1/24`
- Printer: set its network menu to **DHCP/Auto**; NetworkManager will lease an address on this subnet.
- Wi-Fi remains untouched.
- Avoid plugging `eth0` into a regular office/home LAN with an existing DHCP server while this mode is enabled.

From the PT35 itself, open `http://127.0.0.1:8765` and press **Turn DHCP ON** or **Turn DHCP OFF**. Remote web browsers cannot operate these buttons. Alternatively, on the PT35 terminal:

```bash
sudo /usr/local/sbin/pt35-printer-ethernet status
sudo /usr/local/sbin/pt35-printer-ethernet on
sudo /usr/local/sbin/pt35-printer-ethernet off
```

If the Ethernet port has an active network profile or usable IPv4 address, the ON action refuses to replace it automatically. This prevents accidental disruption of an existing Ethernet connection. Disconnect/reconfigure that profile deliberately first if needed.

After switching on, inspect the printer IP via its self-test/network information page, then create its **CUPS queue** using that address/URI. DHCP alone does not automatically register an Epson network printer in CUPS; printer discovery and an appropriate raster/ESC/POS driver are still required. A fixed-IP printer will not request a DHCP lease.

```bash
nmcli device show eth0
lpinfo -v
lpstat -t
```

NetworkManager shared mode can also configure network sharing/NAT as a side effect; **this mode is only intended on a private point-to-point printer cable**. Do not use it on a shared LAN.

## Configure

```bash
sudo nano /etc/pt35-receipt-host.conf
sudo systemctl restart pt35-receipt-host
sudo systemctl status pt35-receipt-host
```

`PT35_PRINTER` should equal an installed CUPS printer queue name (`lpstat -e`). `PT35_WIDTH_DOTS=576` is a common 80 mm printhead width at 203 dpi; change for your printer. This is pixel width **not** paper width.

### Enable local network printing

Connect the PT35 to the desired Wi-Fi normally. Then set:

```ini
PT35_BIND=0.0.0.0
PT35_PASSWORD=replace-this-with-a-long-random-password
```

Restart the service and browse to `http://PT35-IP:8765` from another device on the same network. The HTTP Basic username is `pt35`. **HTTP Basic is not encrypted on ordinary HTTP**: restrict this to a trusted private LAN, preferably protect it with HTTPS via a reverse proxy if used by others. Do **not** forward port 8765 to the Internet. When not sharing, keep the default `127.0.0.1` bind and empty password.

A future edition could add Pi-hosted Wi-Fi hotspot mode; v0.1 expects the Pi to be connected to an existing Wi-Fi network. This version is a printing host, not a Wi-Fi access-point installer.

## Safety & limitations
- Flask/Waitress web service; receives no arbitrary commands, and selects printers only from CUPS queue names.
- Up to 5 MB input photo; up to 16 megapixels source; up to 5000 chars of body text.
- Needs a *working* CUPS queue and suitable driver. Printer-specific cutter, cash drawer, QR ESC/POS sequences are not yet implemented.
- CUPS `lp` accepts PNG only if relevant format filters are installed; test with `lp -d YOUR_QUEUE -o fit-to-page test.png`.
- A job accepted by `lp` may still fail later due to paper or printer connection problems.
- Job history is only kept in RAM and cleared on restart.

## Troubleshooting

```bash
journalctl -u pt35-receipt-host -n 80 --no-pager
lpstat -t
lpinfo -v
```

To disable: `sudo systemctl disable --now pt35-receipt-host`.
