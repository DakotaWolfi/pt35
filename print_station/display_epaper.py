#!/usr/bin/env python3
"""Orange Pi Zero 3W 2.13-inch V4 e-paper: landscape 250x122, upside-down mount."""
import argparse
import json
import logging
from pathlib import Path
import socket
import subprocess
import time
import urllib.request
from PIL import Image, ImageDraw, ImageFont
from epaper_test import Epaper
import challenge

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("fmi.display")
W, H = 250, 122

def font(size, bold=False):
    suffix = "-Bold" if bold else ""
    p = f"/usr/share/fonts/truetype/dejavu/DejaVuSans{suffix}.ttf"
    return ImageFont.truetype(p,size) if Path(p).exists() else ImageFont.load_default()

def icon_printer(draw,x,y,online):
    draw.rectangle((x+2,y+7,x+28,y+21),outline=0,width=2)
    draw.rectangle((x+6,y,x+24,y+8),outline=0,fill=1)
    draw.rectangle((x+7,y+17,x+23,y+27),outline=0,fill=1)
    draw.line((x+9,y+22,x+21,y+22),fill=0)
    if not online: draw.line((x,y,x+30,y+29),fill=0,width=3)

def paste_paw(img, x=218, y=2):
    """Paste the reusable bitmap silhouette as a white mask on black."""
    with Image.open(ROOT / "assets" / "paw.pbm") as original:
        mask = original.convert("L")
    img.paste(1, (x, y), mask)


def render_access_qr(url):
    import qrcode
    from qrcode.constants import ERROR_CORRECT_M
    qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=1, border=4)
    qr.add_data(url)
    qr.make(fit=True)
    raw = qr.make_image(fill_color="black", back_color="white").convert("1")
    scale = 90 // raw.width
    if scale < 1:
        raise ValueError("Guest URL too long for e-paper QR")
    return raw.resize((raw.width * scale, raw.height * scale), Image.Resampling.NEAREST)

def render(state,rotation=180):
    if rotation not in (0,180): raise ValueError("Rotation must be 0 or 180")
    img=Image.new("1",(W,H),1)
    d=ImageDraw.Draw(img)
    d.rectangle((0,0,249,19),fill=0)
    d.text((5,2),"FMI PRINT PET",font=font(12,True),fill=1)
    printing=bool(state.get("printing"))
    online=bool(state.get("printer_ok"))
    status="PRINTING" if printing else ("READY" if online else "OFFLINE")
    mood="EXCITED" if printing else ("HAPPY" if online else "SAD")
    d.polygon([(5,57),(14,30),(32,45),(53,30),(62,57)],fill=1,outline=0)
    d.ellipse((8,41,61,101),outline=0,width=2)
    d.ellipse((21,63,27,70),fill=0)
    d.ellipse((43,63,49,70),fill=0)
    d.polygon([(33,78),(39,78),(36,83)],fill=0)
    d.arc((28,82,46,96),180 if not online else 0,360 if not online else 180,fill=0,width=2)
    d.text((8,106),mood,font=font(9,True),fill=0)
    d.text((69,27),status,font=font(12,True),fill=0)
    d.text((69,44),"Q:{} P:{}".format(state.get("queue",0),state.get("printed",0)),font=font(10),fill=0)
    if state.get("challenge_code"):
        d.text((69,63),"PRINT CODE",font=font(9,True),fill=0)
        d.text((69,78),str(state["challenge_code"]),font=font(17,True),fill=0)
    else:
        d.text((69,74),"AWOO :3",font=font(10,True),fill=0)
    url=state.get("guest_url","")
    if url:
        try:
            import qrcode
            qr=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L,box_size=1,border=4)
            qr.add_data(url);qr.make(fit=True)
            bitmap=qr.make_image(fill_color="black",back_color="white").convert("1")
            scale=max(1,76//bitmap.width)
            bitmap=bitmap.resize((bitmap.width*scale,bitmap.height*scale),Image.Resampling.NEAREST)
            img.paste(bitmap,(W-bitmap.width-2,25))
            d.text((183,106),"SCAN / TAP",font=font(8,True),fill=0)
        except (ImportError, ValueError) as exc:
            LOG.warning("QR unavailable: %s",exc)
    return img.rotate(rotation) if rotation else img

def guest_print_url(conf):
    """Pick explicit guest URL, otherwise current IPv4 of the Wi-Fi link."""
    if conf.get("nfc_url"):
        return str(conf["nfc_url"])
    try:
        raw=subprocess.check_output(["ip","-j","-4","addr","show","dev","wlan0"],
                                     text=True,timeout=2)
        interfaces=json.loads(raw)
        for iface in interfaces:
            for entry in iface.get("addr_info",[]):
                if entry.get("family") == "inet" and entry.get("local"):
                    return "http://{}:{}/".format(entry["local"],int(conf.get("port",8767)))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return ""


def snapshot(conf):
    try:
        with socket.create_connection(__import__("app").printer_destination(conf),timeout=2):
            online=True
    except (OSError, RuntimeError, ValueError): online=False
    try:
        with urllib.request.urlopen("http://127.0.0.1:{}/api/status".format(int(conf.get("port",8767))),timeout=2) as r:
            status=json.load(r)
    except Exception: status={}
    stats=status.get("stats",{})
    try:
        code=challenge.current_code(challenge.get_key()) if conf.get("challenge_enabled") else ""
    except (OSError, ValueError):
        code="------"
    return {"guest_url":guest_print_url(conf),"challenge_code":code,
            "printing":bool(status.get("printing",False)),
            "printer_ok":online,"queue":status.get("queue","?"),
            "printed":stats.get("printed","?"),"dry_run":status.get("dry_run",conf.get("dry_run",True))}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--config",default=str(ROOT/"config.json"))
    p.add_argument("--preview",action="store_true")
    p.add_argument("--once",action="store_true")
    args=p.parse_args()
    conf=json.loads(Path(args.config).read_text())
    setting=conf.get("display",{})
    rotation=int(setting.get("rotation",180))
    delay=max(60,int(setting.get("refresh_interval_seconds",90)))
    logging.basicConfig(level=logging.INFO)
    if args.preview:
        render(snapshot(conf),rotation).save("/tmp/fmi-print-display.png")
        print("Saved /tmp/fmi-print-display.png")
        return
    with Epaper() as epd:
        while True:
            try:
                epd.init()
                state=snapshot(conf)
                if conf.get("nfc_auto_update") and state.get("guest_url") and conf.get("nfc_i2c_bus") is not None:
                    try:
                        from nfc_tag import sync
                        sync(int(conf["nfc_i2c_bus"]), state["guest_url"], allow_write=True)
                    except Exception:
                        LOG.exception("Could not synchronize ST25DV16K guest URL")
                epd.display(render(state,rotation))
                epd.sleep()
                LOG.info("Displayed: %s",state)
            except Exception:
                LOG.exception("Display update failed")
            if args.once: break
            time.sleep(delay)

if __name__=="__main__": main()
