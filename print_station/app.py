#!/usr/bin/env python3
"""FMI Print Station: lightweight LAN/public receipt kiosk, Python standard library."""
import copy
import datetime as dt
import ipaddress
import json
import logging
import os
from pathlib import Path
import queue
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = Path(os.environ.get("FMI_PRINT_CONFIG", ROOT / "config.json"))
DEFAULT = {
    "listen": "127.0.0.1", "port": 8767,
    "access_mode": "local",  # local | public | both
    "local_networks": ["127.0.0.0/8", "::1/128", "192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12"],
    "public_base_url": "", "nfc_url": "",
    "printer_host": "192.168.50.2", "printer_port": 9100,
    "dry_run": True, "cut": True, "feed_lines": 3, "feed_mm": 50,
    "max_message_chars": 160, "max_jobs_per_hour_per_ip": 3,
    "global_min_interval_seconds": 10, "max_queue": 8,
    "station_name": "FMI PRINT STATION", "footer": "AWOO responsibly!",
    "admin_token_env": "FMI_PRINT_ADMIN_TOKEN",
}
LOG = logging.getLogger("fmi.print")
jobs = queue.Queue()
lock = threading.Lock()
history = {}
last_job_at = 0.0
statistics = {"queued": 0, "printed": 0, "failed": 0}

def load_config(path=CONFIG_FILE):
    conf = copy.deepcopy(DEFAULT)
    if path.exists():
        user = json.loads(path.read_text(encoding="utf-8"))
        unknown = set(user) - set(DEFAULT)
        if unknown:
            raise ValueError(f"Unknown configuration keys: {sorted(unknown)}")
        conf.update(user)
    if conf["access_mode"] not in ("local", "public", "both"):
        raise ValueError("access_mode must be local, public or both")
    if not 1 <= int(conf["port"]) <= 65535:
        raise ValueError("Invalid port")
    if not 1 <= int(conf["max_message_chars"]) <= 500:
        raise ValueError("max_message_chars must be 1..500")
    if int(conf["max_queue"]) < 1 or int(conf["max_queue"]) > 50:
        raise ValueError("max_queue must be 1..50")
    if not 0 <= int(conf["feed_mm"]) <= 200:
        raise ValueError("feed_mm must be 0..200")
    for net in conf["local_networks"]:
        ipaddress.ip_network(net, strict=False)
    if conf["access_mode"] in ("public", "both") and not conf["public_base_url"].startswith("https://"):
        raise ValueError("Public mode requires public_base_url with https://")
    if conf["public_base_url"]:
        u = urlsplit(conf["public_base_url"])
        if u.scheme != "https" or not u.netloc or u.username or u.password:
            raise ValueError("public_base_url must be a normal HTTPS URL")
    return conf

def client_is_local(addr, conf):
    try:
        ip = ipaddress.ip_address(addr)
        return any(ip in ipaddress.ip_network(cidr, strict=False) for cidr in conf["local_networks"])
    except ValueError:
        return False

def allowed(addr, conf):
    mode = conf["access_mode"]
    return mode in ("public", "both") or client_is_local(addr, conf)

def make_ticket(name, message, conf):
    # ASCII-only on purpose: reliable across older Epson ESC/POS models.
    def safe(x):
        return "".join(ch if (ord(ch) >= 32 or ch == "\n") else " " for ch in x).encode("ascii", errors="replace").decode("ascii")
    lines = [safe(conf["station_name"])[:42], "-" * 32,
             "AWOO FINE / FMI TICKET", "To: " + safe(name),
             safe(message), "-" * 32, safe(conf["footer"]), ""]
    return "\n".join(lines).encode("ascii")

def send_printer(data, conf):
    if conf["dry_run"]:
        LOG.info("DRY RUN: %r", data)
        return
    # ESC @ initialize, then feed a configurable length before cutting.
    raw = bytes([27, 64]) + data
    dots = round(float(conf["feed_mm"]) * 8)  # Epson 203 dpi is approximately 8 dots/mm
    while dots > 0:
        step = min(255, dots)
        raw += bytes([27, 74, step])  # ESC J n: feed n dots
        dots -= step
    if conf["cut"]:
        raw += bytes([29, 86, 1])
    with socket.create_connection((conf["printer_host"], int(conf["printer_port"])), timeout=5) as conn:
        conn.settimeout(10)
        conn.sendall(raw)

def worker(conf):
    while True:
        entry = jobs.get()
        try:
            send_printer(entry, conf)
            with lock:
                statistics["printed"] += 1
        except Exception:
            LOG.exception("Print failed")
            with lock:
                statistics["failed"] += 1
        finally:
            jobs.task_done()

HTML = """<!doctype html><html lang="en"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta charset="utf-8"><title>FMI Print Station</title>
<style>body{font:16px system-ui,sans-serif;background:#111827;color:#f8fafc;max-width:520px;margin:5vh auto;padding:18px}
main{background:#1f2937;border-radius:18px;padding:22px}input,textarea,button{font:inherit;box-sizing:border-box;width:100%;padding:12px;margin:8px 0;border-radius:9px}
input,textarea{background:#f9fafb;color:#111}button{border:0;background:#f59e0b;color:#111;font-weight:700}
small{color:#cbd5e1}h1{margin-top:0}</style><main><h1>🐺 FMI Print Station</h1>
<p>Issue a very unofficial AWOO ticket.</p><form id="f"><label>Recipient<input name="name" maxlength="40" required placeholder="Suspicious Wolf"></label>
<label>Message<textarea name="message" maxlength="160" rows="3" required placeholder="Unauthorized AWOO detected"></textarea></label>
<button>Print ticket</button></form><p id="status" role="status"></p><small>Parody tickets only · Please don't spam the printer.</small></main>
<script>document.querySelector('#f').onsubmit=async e=>{e.preventDefault();let f=e.target,b=f.querySelector('button');b.disabled=true;
try{let r=await fetch('api/print',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(f)))});let j=await r.json();
document.querySelector('#status').textContent=j.message||j.error||'Unknown response';}catch(err){document.querySelector('#status').textContent='Connection failed';}
finally{b.disabled=false;}}</script></html>"""

class Handler(BaseHTTPRequestHandler):
    conf = DEFAULT
    def reply(self, code, body, mime="application/json"):
        payload = json.dumps(body).encode() if mime == "application/json" else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") else ""))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline' 'self'; style-src 'unsafe-inline' 'self'; object-src 'none'; base-uri 'none'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
    def permitted(self):
        # Reverse proxy must pass the real client IP and enforce its own rate limits.
        # Do NOT trust X-Forwarded-For supplied by arbitrary visitors.
        if not allowed(self.client_address[0], self.conf):
            self.reply(403, {"error": "Local-network access only"})
            return False
        return True
    def do_GET(self):
        if not self.permitted(): return
        path = urlsplit(self.path).path
        if path == "/":
            self.reply(200, HTML, "text/html")
        elif path == "/api/status":
            with lock:
                snapshot = dict(statistics)
            self.reply(200, {"station": self.conf["station_name"], "queue": jobs.qsize(),
                             "dry_run": self.conf["dry_run"], "stats": snapshot,
                             "nfc_url": self.conf["nfc_url"] or self.conf["public_base_url"]})
        else: self.reply(404, {"error": "Not found"})
    def do_POST(self):
        if not self.permitted(): return
        if urlsplit(self.path).path != "/api/print":
            return self.reply(404, {"error": "Not found"})
        # Same-origin check prevents common cross-site drive-by printing.
        origin = self.headers.get("Origin")
        if origin:
            host = self.headers.get("Host", "")
            expected = {"http://" + host, "https://" + host}
            if self.conf["public_base_url"]:
                expected.add(self.conf["public_base_url"].rstrip("/"))
            if origin.rstrip("/") not in expected:
                return self.reply(403, {"error": "Origin not allowed"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > 2048:
                return self.reply(413, {"error": "Invalid request size"})
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                return self.reply(415, {"error": "JSON required"})
            payload = json.loads(self.rfile.read(size))
            name = str(payload.get("name", "")).strip()
            message = str(payload.get("message", "")).strip()
            if not (1 <= len(name) <= 40 and 1 <= len(message) <= self.conf["max_message_chars"]):
                return self.reply(400, {"error": "Enter a name and a shorter message"})
            if any(ord(ch) < 32 and ch not in "\n\t" for ch in name + message):
                return self.reply(400, {"error": "Invalid control characters"})
            global last_job_at
            now = time.monotonic()
            ip = self.client_address[0]
            with lock:
                history[ip] = [t for t in history.get(ip, []) if now - t < 3600]
                if len(history[ip]) >= self.conf["max_jobs_per_hour_per_ip"]:
                    return self.reply(429, {"error": "Hourly limit reached"})
                if now - last_job_at < self.conf["global_min_interval_seconds"]:
                    return self.reply(429, {"error": "Printer cooldown; try again shortly"})
                if jobs.full():
                    return self.reply(503, {"error": "Printer queue full"})
                jobs.put_nowait(make_ticket(name, message, self.conf))
                history[ip].append(now)
                last_job_at = now
                statistics["queued"] += 1
            return self.reply(202, {"message": "Ticket queued!", "queue": jobs.qsize()})
        except (ValueError, TypeError, json.JSONDecodeError):
            return self.reply(400, {"error": "Invalid JSON data"})

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--config", default=str(CONFIG_FILE))
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    conf = load_config(Path(args.config))
    jobs.maxsize = conf["max_queue"]
    Handler.conf = conf
    threading.Thread(target=worker, args=(conf,), daemon=True).start()
    server = ThreadingHTTPServer((conf["listen"], int(conf["port"])), Handler)
    LOG.info("Print station on http://%s:%s (mode=%s dry_run=%s)",
             conf["listen"], conf["port"], conf["access_mode"], conf["dry_run"])
    server.serve_forever()

if __name__ == "__main__":
    main()
