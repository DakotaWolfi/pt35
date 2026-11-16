#!/usr/bin/env python3
"""Orange Pi Zero 3W 2.13-inch V4 e-paper: landscape 250x122, upside-down mount."""
import argparse
import json
import logging
from pathlib import Path
import socket
import time
import urllib.request
from PIL import Image, ImageDraw, ImageFont
from epaper_test import Epaper

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

def render(state,rotation=180):
    img=Image.new("1",(W,H),1)
    d=ImageDraw.Draw(img)
    d.rectangle((0,0,W-1,28),fill=0)
    d.text((7,5),"FMI PRINT STATION",font=font(14,True),fill=1)
    paste_paw(img)
    d.text((9,34),"AWOO FINE OFFICE",font=font(12,True),fill=0)
    d.line((8,53,242,53),fill=0)
    online=state.get("printer_ok",False)
    icon_printer(d,10,62,online)
    d.text((48,59),"PRINTER READY" if online else "PRINTER OFFLINE",
           font=font(13,True),fill=0)
    d.text((48,82),"QUEUE {}  PRINTED {}".format(state.get("queue","?"),
                                                    state.get("printed","?")),
           font=font(11),fill=0)
    d.line((8,101,242,101),fill=0)
    d.text((9,105),("DRY RUN" if state.get("dry_run",True) else "LIVE")
           +"  |  LOCAL NETWORK",font=font(10),fill=0)
    if rotation not in (0,180): raise ValueError("Rotation must be 0 or 180")
    return img.rotate(rotation) if rotation else img

def snapshot(conf):
    try:
        with socket.create_connection((conf["printer_host"],int(conf["printer_port"])),timeout=2):
            online=True
    except OSError: online=False
    try:
        with urllib.request.urlopen("http://127.0.0.1:{}/api/status".format(int(conf.get("port",8767))),timeout=2) as r:
            status=json.load(r)
    except Exception: status={}
    stats=status.get("stats",{})
    return {"printer_ok":online,"queue":status.get("queue","?"),
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
                epd.display(render(state,rotation))
                epd.sleep()
                LOG.info("Displayed: %s",state)
            except Exception:
                LOG.exception("Display update failed")
            if args.once: break
            time.sleep(delay)

if __name__=="__main__": main()
