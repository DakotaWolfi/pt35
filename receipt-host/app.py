#!/usr/bin/env python3
"""PT35 Receipt Host: small LAN-capable CUPS receipt printing web app."""
import hmac
import io
import os
import secrets
import subprocess
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from PIL import Image, ImageDraw, ImageFont, ImageOps

app = Flask(__name__)
app.secret_key = os.environ.get('PT35_SESSION_KEY', os.urandom(32))
BIND = os.environ.get('PT35_BIND', '127.0.0.1')
PORT = int(os.environ.get('PT35_PORT', '8765'))
SHARE_PASSWORD = os.environ.get('PT35_PASSWORD', '')
DEFAULT_PRINTER = os.environ.get('PT35_PRINTER', '')
DOTS = max(200, min(1024, int(os.environ.get('PT35_WIDTH_DOTS', '576'))))
MAX_IMAGE_BYTES = 5 * 1024 * 1024
JOBS = deque(maxlen=40)
JOBS_LOCK = threading.Lock()
ETHERNET_HELPER = '/usr/local/sbin/pt35-printer-ethernet'
FONT_FILES = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf',
]


def cups_printers():
    try:
        result = subprocess.run(['lpstat', '-e'], capture_output=True, text=True, timeout=5, check=True)
        return [name.strip() for name in result.stdout.splitlines() if name.strip()]
    except (OSError, subprocess.SubprocessError):
        return []


def valid_printer(selected):
    choices = cups_printers()
    if not choices:
        raise ValueError('No CUPS printer configured. Add one in CUPS first.')
    if selected not in choices:
        raise ValueError('Choose one of the configured CUPS printers.')
    return selected


def font(size=22):
    for filename in FONT_FILES:
        if Path(filename).exists():
            return ImageFont.truetype(filename, size)
    return ImageFont.load_default()


def wrap_text(draw, text, text_font, width):
    lines = []
    for paragraph in text.split('\n'):
        if not paragraph:
            lines.append('')
            continue
        current = ''
        for word in paragraph.split():
            candidate = (current + ' ' + word).strip()
            if draw.textbbox((0, 0), candidate, font=text_font)[2] <= width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = ''
                for char in word:
                    test = current + char
                    if current and draw.textbbox((0, 0), test, font=text_font)[2] > width:
                        lines.append(current)
                        current = char
                    else:
                        current = test
        lines.append(current)
    return lines


def build_receipt(title, body, image_file=None):
    if len(title) > 100 or len(body) > 5000:
        raise ValueError('Text too long (title <= 100, body <= 5000 characters).')
    pad = 18
    normal = font(22)
    heading = font(31)
    scratch = Image.new('RGB', (DOTS, 100), 'white')
    d = ImageDraw.Draw(scratch)
    body_lines = wrap_text(d, body, normal, DOTS - 2 * pad)
    title_lines = wrap_text(d, title.strip() or 'PT35 RECEIPT', heading, DOTS - 2 * pad)
    im = None
    img_h = 0
    if image_file and image_file.filename:
        raw = image_file.stream.read(MAX_IMAGE_BYTES + 1)
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError('Image is larger than 5 MB.')
        try:
            im = Image.open(io.BytesIO(raw))
            im.verify()
            im = Image.open(io.BytesIO(raw))
            if im.width * im.height > 16_000_000:
                raise ValueError('Image has too many pixels.')
            im = ImageOps.exif_transpose(im).convert('RGB')
            im.thumbnail((DOTS - 2 * pad, 950))
            img_h = im.height + 18
        except (OSError, ValueError) as exc:
            raise ValueError(f'Invalid image: {exc}') from exc
    height = 40 + len(title_lines) * 44 + 18 + len(body_lines) * 31 + img_h + 60
    if height > 14000:
        raise ValueError('Receipt too tall.')
    canvas = Image.new('RGB', (DOTS, height), 'white')
    draw = ImageDraw.Draw(canvas)
    y = 24
    for line in title_lines:
        draw.text((pad, y), line, font=heading, fill='black')
        y += 44
    draw.line((pad, y + 3, DOTS - pad, y + 3), fill='black', width=2)
    y += 21
    for line in body_lines:
        draw.text((pad, y), line, font=normal, fill='black')
        y += 31
    if im is not None:
        y += 12
        canvas.paste(im, ((DOTS - im.width) // 2, y))
        y += img_h
    return canvas.crop((0, 0, DOTS, min(height, y + 45))).convert('1', dither=Image.Dither.FLOYDSTEINBERG)


def submit_cups(image, printer):
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    result = subprocess.run(
        ['lp', '-d', printer, '-t', 'PT35 receipt', '-o', 'fit-to-page'],
        input=buffer.getvalue(), capture_output=True, timeout=30
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', 'replace').strip() or 'lp failed')
    return result.stdout.decode('utf-8', 'replace').strip()


@app.before_request
def authenticate():
    if request.path == '/health':
        return None
    if BIND not in ('127.0.0.1', 'localhost', '::1') and not SHARE_PASSWORD:
        abort(503, description='Network sharing requires PT35_PASSWORD.')
    if SHARE_PASSWORD:
        supplied = request.authorization.password if request.authorization else ''
        username = request.authorization.username if request.authorization else ''
        if not (hmac.compare_digest(username, 'pt35') and hmac.compare_digest(supplied, SHARE_PASSWORD)):
            return ('Authentication required', 401, {'WWW-Authenticate': 'Basic realm="PT35 Receipt Host"'})
    return None


@app.get('/health')
def health():
    return {'status': 'ok'}


def ethernet_status():
    try:
        result = subprocess.run(
            [ETHERNET_HELPER, 'status'], capture_output=True, text=True, timeout=5
        )
        if result.returncode:
            return 'unavailable'
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 'unavailable'


@app.post('/ethernet')
def ethernet_toggle():
    # Never allow a remote web client to change the PT35 network configuration.
    if request.remote_addr not in ('127.0.0.1', '::1'):
        abort(403, description='Ethernet DHCP changes require the PT35 local browser.')
    if not hmac.compare_digest(request.form.get('csrf', ''), session.get('csrf', '')):
        abort(403, description='Invalid form token')
    action = request.form.get('action', '')
    if action not in ('on', 'off'):
        abort(400)
    try:
        result = subprocess.run(
            ['sudo', '-n', ETHERNET_HELPER, action],
            capture_output=True, text=True, timeout=25
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or 'NetworkManager operation failed')
        flash(result.stdout.strip() or 'Ethernet DHCP updated', 'success')
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('index'))


@app.get('/')
def index():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_urlsafe(32)
    printers = cups_printers()
    current = DEFAULT_PRINTER if DEFAULT_PRINTER in printers else (printers[0] if printers else '')
    with JOBS_LOCK:
        jobs = list(JOBS)
    return render_template('index.html', printers=printers, selected=current, jobs=jobs, dots=DOTS, ethernet=ethernet_status(), csrf=session['csrf'], local=request.remote_addr in ('127.0.0.1', '::1'))


@app.post('/print')
def print_receipt():
    if request.content_length and request.content_length > MAX_IMAGE_BYTES + 20000:
        abort(413)
    title = request.form.get('title', '')
    body = request.form.get('body', '')
    selected = request.form.get('printer', '')
    if not body.strip() and not title.strip() and not (request.files.get('image') and request.files['image'].filename):
        flash('Enter some text or upload an image.', 'error')
        return redirect(url_for('index'))
    try:
        printer = valid_printer(selected)
        receipt = build_receipt(title, body, request.files.get('image'))
        outcome = submit_cups(receipt, printer)
        with JOBS_LOCK:
            JOBS.appendleft({'time': datetime.now().strftime('%H:%M:%S'), 'printer': printer,
                             'title': title[:50] or '(untitled)', 'result': outcome[:150]})
        flash(f'Sent to {printer}: {outcome}', 'success')
    except (ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        flash(str(exc), 'error')
    return redirect(url_for('index'))


if __name__ == '__main__':
    from waitress import serve
    serve(app, host=BIND, port=PORT, threads=4)
