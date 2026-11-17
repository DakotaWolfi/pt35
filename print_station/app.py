#!/usr/bin/env python3
"""FMI Print Station: lightweight LAN/public receipt kiosk, Python standard library."""
import copy
import base64
import hmac
import io
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
import receipt_store
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = Path(os.environ.get("FMI_PRINT_CONFIG", ROOT / "config.json"))
DEFAULT = {
    "listen": "127.0.0.1", "port": 8767, "admin_port": 8768,
    "access_mode": "local",  # local | public | both
    "local_networks": ["127.0.0.0/8", "::1/128", "192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12"],
    "public_base_url": "", "nfc_url": "",
    "printer_host": "192.168.50.2", "printer_port": 9100,
    "dry_run": True, "cut": True, "feed_lines": 3, "feed_mm": 50,
    "max_message_chars": 160, "max_jobs_per_hour_per_ip": 3,
    "global_min_interval_seconds": 10, "max_queue": 8,
    "station_name": "FMI PRINT STATION", "footer": "AWOO responsibly!",
    "admin_token_env": "FMI_PRINT_ADMIN_TOKEN",
    "admin_token": "", "logo_enabled": True, "logo_width": 384,
    "subtitle": "Department of Unlicensed Howling",
    "default_amount": "350.00", "currency": "CHF",
    "display": {"enabled": True, "rotation": 180, "refresh_interval_seconds": 90},
    "require_https_proxy": False,  # enable ONLY after trusted TLS proxy is online
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
    if not 1 <= int(conf["admin_port"]) <= 65535 or int(conf["admin_port"]) == int(conf["port"]):
        raise ValueError("admin_port must be a distinct valid port")
    if not 1 <= int(conf["port"]) <= 65535:
        raise ValueError("Invalid port")
    if not 1 <= int(conf["max_message_chars"]) <= 500:
        raise ValueError("max_message_chars must be 1..500")
    if int(conf["max_queue"]) < 1 or int(conf["max_queue"]) > 50:
        raise ValueError("max_queue must be 1..50")
    if int(conf["logo_width"]) not in (256, 384, 512, 576):
        raise ValueError("logo_width must be 256, 384, 512 or 576")
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
    if conf["require_https_proxy"] and conf["listen"] not in ("127.0.0.1", "::1"):
        raise ValueError("HTTPS proxy mode requires a loopback-only listen address")
    return conf

def request_identity(handler):
    """Trust forwarded client IP only when a localhost reverse proxy connects."""
    peer = handler.client_address[0]
    via_local_proxy = (bool(getattr(handler, "admin_listener", False)) or bool(handler.conf.get("require_https_proxy"))) and peer in ("127.0.0.1", "::1")
    if via_local_proxy:
        forwarded = handler.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        try:
            ipaddress.ip_address(forwarded)
            return forwarded
        except ValueError:
            return peer
    return peer

def client_is_local(addr, conf):
    try:
        ip = ipaddress.ip_address(addr)
        return any(ip in ipaddress.ip_network(cidr, strict=False) for cidr in conf["local_networks"])
    except ValueError:
        return False

def allowed(addr, conf):
    mode = conf["access_mode"]
    return mode in ("public", "both") or client_is_local(addr, conf)

def make_ticket(name, message, conf, details=None):
    # ASCII-only on purpose: reliable across older Epson ESC/POS models.
    def safe(x):
        return "".join(ch if (ord(ch) >= 32 or ch == "\n") else " " for ch in x).encode("ascii", errors="replace").decode("ascii")
    details = details or {}
    lines = [safe(conf["station_name"])[:42], safe(conf.get("subtitle", ""))[:42],
             "-" * 32, "AWOO FINE / FMI TICKET", "To: " + safe(name)]
    for title, key in (("Issued by", "issuer"), ("Location", "location"),
                       ("Offence", "offence"), ("Amount", "amount")):
        value = safe(str(details.get(key, "")))[:80]
        if value:
            lines.append(title + ": " + value)
    lines += [safe(message), "-" * 32, safe(conf["footer"]), ""]
    return "\n".join(lines).encode("ascii")

def raster_image_block(png_b64):
    """Decode a strictly limited PNG and emit Epson GS v 0 raster bytes."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        binary = base64.b64decode(png_b64, validate=True)
        with Image.open(io.BytesIO(binary)) as im:
            if im.format != "PNG" or im.width > 384 or im.height > 240 or im.width < 1 or im.height < 1:
                raise ValueError("Image must be a PNG at most 384 x 240")
            im.load()
            rgba = im.convert("RGBA")
        on_white = Image.new("RGBA", rgba.size, "white")
        on_white.alpha_composite(rgba)
        bw = ImageOps.grayscale(on_white.convert("RGB")).point(lambda v: 255 if v >= 150 else 0)
        w,h=bw.size
        stride=(w+7)//8
        dots=bytearray(stride*h)
        px=bw.load()
        for y in range(h):
            for x in range(w):
                if px[x,y] == 0:
                    dots[y*stride+x//8] |= 0x80 >> (x%8)
        return bytes([27,97,1,29,118,48,0,stride&255,stride>>8,h&255,h>>8])+dots+b"\n"
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        raise ValueError("Invalid custom receipt PNG") from exc

def make_custom_receipt(payload, conf):
    """Render text and limited bitmap blocks in their requested receipt order."""
    title = clean_line(payload.get("title", "CUSTOM RECEIPT"), 48)
    subtitle = clean_line(payload.get("subtitle", ""), 64)
    footer = clean_line(payload.get("footer", conf["footer"]), 100)
    result = bytearray((title + "\n" + (subtitle+"\n" if subtitle else "") + "-"*32+"\n").encode("ascii"))
    for item in payload.get("lines", []):
        kind=item["type"]
        value=clean_line(item.get("text", ""),160)
        if kind=="image":
            result.extend(raster_image_block(item["image"]))
            continue
        if kind=="rule": value="-"*32
        elif kind=="blank": value=""
        elif kind=="heading": value=value.upper()[:42]
        elif kind=="pair": value=clean_line(item.get("label",""),40)+": "+value
        result.extend((value+"\n").encode("ascii", errors="replace"))
    result.extend(("-"*32+"\n"+footer+"\n").encode("ascii",errors="replace"))
    return bytes(result)

def custom_receipt_text(payload):
    """Human-readable audit preview; image binary is in payload lines, not text."""
    lines=[payload["title"],payload.get("subtitle",""),"-"*32]
    for item in payload["lines"]:
        k=item["type"]
        if k=="image": lines.append("[IMAGE: PNG, embedded in saved receipt]")
        elif k=="rule": lines.append("-"*32)
        elif k=="blank": lines.append("")
        elif k=="pair": lines.append(item.get("label","")+": "+item.get("text",""))
        elif k=="heading": lines.append(item.get("text","").upper())
        else: lines.append(item.get("text",""))
    return "\n".join(lines+["-"*32,payload.get("footer","")])

def clean_line(value, limit):
    return "".join(c if 32 <= ord(c) < 127 else "?" for c in str(value))[:limit]

def validate_custom(payload, conf):
    title = str(payload.get("title", "")).strip()
    items = payload.get("lines", [])
    if not (1 <= len(title) <= 48 and isinstance(items, list) and 1 <= len(items) <= 25):
        raise ValueError("Custom receipt needs a title and 1-25 lines")
    allowed_types = {"text", "heading", "pair", "rule", "blank", "image"}
    clean_items=[]
    image_count=0
    total_binary=0
    for entry in items:
        if not isinstance(entry,dict) or entry.get("type") not in allowed_types:
            raise ValueError("Unsupported receipt item")
        typ=entry["type"]
        v=str(entry.get("text",""))
        label=str(entry.get("label",""))
        if len(v)>160 or len(label)>40 or "\n" in v or "\n" in label or "\r" in v or "\r" in label:
            raise ValueError("Receipt item too long")
        if typ in ("text","heading","pair") and not v.strip():
            raise ValueError("Receipt line cannot be empty")
        clean={"type":typ,"text":v,"label":label}
        if typ=="image":
            image_count+=1
            if image_count>2:
                raise ValueError("Maximum 2 images per receipt")
            png=str(entry.get("image",""))
            if len(png)>44000:
                raise ValueError("Image exceeds 32 KiB")
            total_binary+=len(png)
            if total_binary>65000:
                raise ValueError("Receipt images too large")
            # Decode and validate before placing job in queue or history.
            raster_image_block(png)
            clean["image"]=png
        clean_items.append(clean)
    return {"title":title,"subtitle":str(payload.get("subtitle",""))[:64],
            "footer":str(payload.get("footer",conf["footer"]))[:100],
            "lines":clean_items}

def send_printer(data, conf):
    if conf["dry_run"]:
        LOG.info("DRY RUN: %r", data)
        return
    # ESC @ initialize, then feed a configurable length before cutting.
    raw = bytes([27, 64])
    if conf.get("logo_enabled") and (ROOT / "header_logo.png").exists():
        try:
            raw += raster_logo(ROOT / "header_logo.png", int(conf.get("logo_width", 384)))
        except Exception:
            LOG.exception("Could not rasterize header logo")
    raw += data
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

def raster_logo(path, max_width):
    from PIL import Image, ImageOps
    with Image.open(path) as source:
        source.load()
        img = source.convert("RGBA")
    white = Image.new("RGBA", img.size, "white")
    white.alpha_composite(img)
    gray = ImageOps.grayscale(white.convert("RGB"))
    ratio = min(1.0, max_width / gray.width, 240 / gray.height)
    if ratio < 1:
        gray = gray.resize((max(1, round(gray.width * ratio)),
                            max(1, round(gray.height * ratio))), Image.Resampling.LANCZOS)
    width, height = gray.size
    row_bytes = (width + 7) // 8
    data = bytearray(row_bytes * height)
    pixels = gray.load()
    for y in range(height):
        for x in range(width):
            if pixels[x, y] < 150:
                data[y * row_bytes + x // 8] |= 0x80 >> (x % 8)
    return (bytes([27, 97, 1, 29, 118, 48, 0,
                   row_bytes & 255, row_bytes >> 8,
                   height & 255, height >> 8]) + data + b"\n")

def admin_allowed(handler):
    configured = handler.conf.get("admin_token") or os.environ.get(handler.conf.get("admin_token_env", "FMI_PRINT_ADMIN_TOKEN"), "")
    provided = handler.headers.get("X-FMI-Admin", "")
    return bool(configured) and hmac.compare_digest(str(configured), provided)

def public_config(conf):
    keys = ("station_name", "subtitle", "footer", "printer_host", "printer_port",
            "dry_run", "cut", "feed_mm", "logo_enabled", "logo_width",
            "default_amount", "currency")
    return {key: conf.get(key) for key in keys}

def worker(conf):
    while True:
        entry = jobs.get()
        job_id, raw = entry
        try:
            send_printer(raw, conf)
            receipt_store.complete(job_id, True)
            with lock:
                statistics["printed"] += 1
        except Exception as exc:
            LOG.exception("Print failed")
            try: receipt_store.complete(job_id, False, str(exc))
            except Exception: LOG.exception("Could not record failed job")
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
    admin_listener = False
    def admin_transport(self):
        return (self.admin_listener and self.client_address[0] in ("127.0.0.1", "::1")
                and self.headers.get("X-Forwarded-Proto","").lower() == "https")
    def require_secure_admin(self):
        if self.admin_transport(): return True
        self.reply(403, {"error": "Administrator functions require HTTPS; use the secured admin URL"})
        return False
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
        if self.conf.get("require_https_proxy"):
            internal_status = (urlsplit(self.path).path == "/api/status" and
                               self.client_address[0] in ("127.0.0.1", "::1") and
                               not self.headers.get("X-Forwarded-For"))
            if not internal_status and (self.client_address[0] not in ("127.0.0.1", "::1") or self.headers.get("X-Forwarded-Proto","").lower() != "https"):
                self.reply(403, {"error": "HTTPS required"})
                return False
        if not allowed(self.client_address[0], self.conf):
            self.reply(403, {"error": "Local-network access only"})
            return False
        return True
    def do_GET(self):
        if not self.permitted(): return
        path = urlsplit(self.path).path
        if path in ("/", "/fines", "/custom", "/history", "/settings"):
            self.reply(200, (ROOT / "index.html").read_text(encoding="utf-8"), "text/html")
        elif path == "/api/logo":
            logo = ROOT / "header_logo.png"
            if not logo.exists():
                return self.reply(404, {"error": "No logo"})
            content = logo.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        elif path == "/api/history":
            if not self.require_secure_admin(): return
            if not admin_allowed(self):
                LOG.warning("Unauthorized history access from %s", request_identity(self))
                return self.reply(403, {"error": "Admin token required"})
            self.reply(200, {"jobs": receipt_store.list_jobs(60)})
        elif path.startswith("/api/history/"):
            if not self.require_secure_admin(): return
            if not admin_allowed(self):
                LOG.warning("Unauthorized receipt access from %s", request_identity(self))
                return self.reply(403, {"error": "Admin token required"})
            try: job_id = int(path.rsplit("/",1)[1])
            except ValueError: return self.reply(400, {"error": "Invalid job ID"})
            item = receipt_store.get_job(job_id)
            if item is None: return self.reply(404, {"error": "Job not found"})
            self.reply(200, item)
        elif path == "/api/settings":
            if not self.require_secure_admin(): return
            if not admin_allowed(self):
                return self.reply(403, {"error": "Admin token required"})
            self.reply(200, public_config(self.conf))
        elif path == "/api/status":
            with lock:
                snapshot = dict(statistics)
            self.reply(200, {"station": self.conf["station_name"], "queue": jobs.qsize(),
                             "dry_run": self.conf["dry_run"], "stats": snapshot,
                             "nfc_url": self.conf["nfc_url"] or self.conf["public_base_url"]})
        else: self.reply(404, {"error": "Not found"})
    def do_POST(self):
        if not self.permitted(): return
        if urlsplit(self.path).path not in ("/api/print", "/api/custom", "/api/settings", "/api/logo", "/api/logo/remove", "/api/probe"):
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
            if size < 1 or size > (2500000 if urlsplit(self.path).path == "/api/logo" else (85000 if urlsplit(self.path).path == "/api/custom" else 4096)):
                return self.reply(413, {"error": "Invalid request size"})
            if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                return self.reply(415, {"error": "JSON required"})
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                return self.reply(400, {"error": "JSON object required"})
            path = urlsplit(self.path).path
            if path in ("/api/settings", "/api/logo", "/api/logo/remove", "/api/probe"):
                if not self.require_secure_admin(): return
                if not admin_allowed(self):
                    return self.reply(403, {"error": "Admin token required"})
                if path == "/api/probe":
                    with socket.create_connection((self.conf["printer_host"],
                            int(self.conf["printer_port"])), timeout=3):
                        pass
                    return self.reply(200, {"message": "Printer connected"})
                if path == "/api/settings":
                    allowed_keys = set(public_config(self.conf))
                    changed = {k: v for k, v in payload.items() if k in allowed_keys}
                    if not 0 <= float(changed.get("feed_mm", self.conf["feed_mm"])) <= 200:
                        return self.reply(400, {"error": "Feed must be 0-200 mm"})
                    if int(changed.get("logo_width", self.conf["logo_width"])) not in (256,384,512,576):
                        return self.reply(400, {"error": "Unsupported logo width"})
                    changed["printer_port"] = int(changed.get("printer_port", self.conf["printer_port"]))
                    if not 1 <= changed["printer_port"] <= 65535:
                        return self.reply(400, {"error": "Invalid port"})
                    for name_key in ("station_name", "subtitle", "footer"):
                        if name_key in changed:
                            changed[name_key] = str(changed[name_key])[:160]
                    self.conf.update(changed)
                    target = ROOT / "config.json"
                    saved = json.loads(target.read_text()) if target.exists() else {}
                    saved.update(changed)
                    temp = target.with_suffix(".json.tmp")
                    temp.write_text(json.dumps(saved, indent=2) + "\n")
                    temp.replace(target)
                    return self.reply(200, public_config(self.conf))
                logo = ROOT / "header_logo.png"
                if path == "/api/logo/remove":
                    logo.unlink(missing_ok=True)
                    return self.reply(200, {"message": "Logo removed"})
                data = base64.b64decode(payload.get("data", ""), validate=True)
                if len(data) > 1500000:
                    return self.reply(413, {"error": "Image too large (1.5 MB max)"})
                from PIL import Image
                with Image.open(io.BytesIO(data)) as original:
                    original.verify()
                with Image.open(io.BytesIO(data)) as original:
                    if original.width * original.height > 12000000:
                        return self.reply(413, {"error": "Too many pixels"})
                    img = original.convert("RGBA")
                    img.thumbnail((1200, 700))
                    img.save(logo, "PNG", optimize=True)
                return self.reply(200, {"message": "Header image saved"})
            kind = "custom" if path == "/api/custom" else "fine"
            if kind == "custom":
                try: receipt = validate_custom(payload, self.conf)
                except ValueError as exc: return self.reply(400, {"error": str(exc)})
                raw = make_custom_receipt(receipt, self.conf)
            else:
                name = str(payload.get("name", "")).strip()
                message = str(payload.get("message", "")).strip()
                if not (1 <= len(name) <= 40 and 1 <= len(message) <= self.conf["max_message_chars"]):
                    return self.reply(400, {"error": "Enter a name and a shorter message"})
                if any(ord(ch) < 32 and ch not in "\n\t" for ch in name + message):
                    return self.reply(400, {"error": "Invalid control characters"})
                details = {}
                for key in ("issuer", "location", "offence"):
                    details[key] = str(payload.get(key, ""))[:80]
                amount = str(payload.get("amount", ""))[:24]
                currency = str(payload.get("currency", "CHF"))[:8]
                details["amount"] = (currency + " " + amount) if amount else ""
                receipt = {"name": name, "message": message, **details,
                           "amount": amount, "currency": currency}
                raw = make_ticket(name, message, self.conf, details)
            receipt["device_name"] = str(payload.get("device_name","")).strip()[:64]
            receipt["rendered_text"] = raw.decode("ascii",errors="replace") if kind=="fine" else custom_receipt_text(receipt)
            receipt["print_options"] = {"feed_mm": self.conf["feed_mm"], "cut": self.conf["cut"],
                                        "dry_run": self.conf["dry_run"],
                                        "logo_enabled": self.conf.get("logo_enabled",False)}
            global last_job_at
            now = time.monotonic()
            ip = request_identity(self)
            with lock:
                history[ip] = [t for t in history.get(ip, []) if now - t < 3600]
                if len(history[ip]) >= self.conf["max_jobs_per_hour_per_ip"]:
                    return self.reply(429, {"error": "Hourly limit reached"})
                if now - last_job_at < self.conf["global_min_interval_seconds"]:
                    return self.reply(429, {"error": "Printer cooldown; try again shortly"})
                if jobs.full():
                    return self.reply(503, {"error": "Printer queue full"})
                job_id = receipt_store.record(kind, receipt, source_ip=ip,
                                              user_agent=self.headers.get("User-Agent", ""))
                jobs.put_nowait((job_id, raw))
                history[ip].append(now)
                last_job_at = now
                statistics["queued"] += 1
            return self.reply(202, {"message": "Receipt queued!", "id": job_id, "queue": jobs.qsize()})
        except Exception as exc:
            LOG.warning("Request rejected: %s", exc)
            return self.reply(400, {"error": "Invalid JSON data"})

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--config", default=str(CONFIG_FILE))
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    conf = load_config(Path(args.config))
    with receipt_store.connection() as db: pass
    jobs.maxsize = conf["max_queue"]
    Handler.conf = conf
    threading.Thread(target=worker, args=(conf,), daemon=True).start()
    # Two independent listening sockets: the publicly reachable HTTP port NEVER
    # serves administrator APIs. An HTTPS reverse proxy talks only to localhost.
    class AdminHandler(Handler):
        admin_listener = True
    AdminHandler.conf = conf
    admin_server = ThreadingHTTPServer(("127.0.0.1", int(conf["admin_port"])), AdminHandler)
    threading.Thread(target=admin_server.serve_forever, daemon=True).start()
    server = ThreadingHTTPServer((conf["listen"], int(conf["port"])), Handler)
    LOG.info("Guest HTTP on %s:%s; HTTPS admin proxy upstream 127.0.0.1:%s", conf["listen"],conf["port"],conf["admin_port"])
    server.serve_forever()

if __name__ == "__main__":
    main()
