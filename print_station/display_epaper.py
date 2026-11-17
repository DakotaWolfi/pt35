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
from pet_activity import current as pet_activity

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
    """Monochrome 250x122 display: wolf | state | QR and web code."""
    if rotation not in (0,180):raise ValueError("Rotation must be 0 or 180")
    img=Image.new("1",(W,H),1)
    d=ImageDraw.Draw(img)
    printing=bool(state.get("printing"))
    online=bool(state.get("printer_ok"))
    activity=state.get("activity","idle")
    # One operational status only; Q/P appear once in the header.
    modes={
        "error":("annoyed","GRUMPY","PRINT ERROR"),
        "printing":("startled","EXCITED","PRINTING!"),
        "printed":("smug","PROUD","GOOD JOB!"),
        "nfc":("curious","CURIOUS","NFC HELLO!"),
        "pair":("listening","CURIOUS","PAIRING"),
        "nfc_print":("startled","EXCITED","NFC RECEIPT"),
        "web":("social","SOCIAL","WEB VISITOR"),
        "web_print":("startled","EXCITED","WEB RECEIPT"),
        "idle":("happy","HAPPY","AWOO :3"),
    }
    face,mood,event=modes.get(activity,modes["idle"])
    if not online:face,mood,event="annoyed","SAD","PRINTER OFF"
    elif printing:face,mood,event="startled","EXCITED","PRINTING!"
    d.rectangle((0,0,249,19),fill=0)
    d.text((4,3),"FMI PRINT PET",font=font(11,True),fill=1)
    short_status=("PRINT" if printing else ("OFF" if not online else "READY"))
    d.text((139,4),short_status,font=font(9,True),fill=1)
    d.text((188,4),"Q:{} P:{}".format(state.get("queue",0),state.get("printed",0)),
           font=font(8,True),fill=1)
    d.line((70,21,70,121),fill=0,width=1)
    sprites=ROOT/"assets"/"wolves"
    sprite=sprites/("wolf_"+face+".png")
    if not sprite.exists():sprite=sprites/"wolf_idle.png"
    if sprite.exists():
        from PIL import ImageOps
        with Image.open(sprite) as original:
            art=original.convert("RGBA")
            white=Image.new("RGBA",art.size,"white")
            white.alpha_composite(art)
            artwork=ImageOps.grayscale(white.convert("RGB"))
            artwork.thumbnail((65,77),Image.Resampling.LANCZOS)
            bw=artwork.point(lambda level:255 if level>=155 else 0).convert("1")
            img.paste(bw,((70-bw.width)//2,23+(77-bw.height)//2))
    else:
        d.rectangle((4,24,66,95),outline=0,width=1)
        d.text((12,54),"PET?",font=font(12,True),fill=0)
        LOG.warning("Wolf sprite missing: fetch_collarpet_assets.sh")
    d.text((5,105),mood,font=font(9,True),fill=0)
    d.line((174,21,174,121),fill=0,width=1)
    # Middle: dynamic pet message, never another copy of READY / Q / P.
    d.text((75,30),event[:14],font=font(11,True),fill=0)
    d.line((76,48,168,48),fill=0,width=1)
    if state.get("pair_armed"):
        lines=("PAIR ARMED","TAP PT35")
    elif activity in ("nfc","pair"):
        lines=("NFC MAILBOX","LINK ACTIVE")
    elif activity in ("web","web_print"):
        lines=("GUEST PAGE","WEB ACTIVITY")
    else:
        lines=("NFC PAIRED" if state.get("nfc_paired") else "NFC READY",
               "SCAN QR ->")
    d.text((75,59),lines[0],font=font(9,True),fill=0)
    d.text((75,78),lines[1],font=font(9),fill=0)
    if state.get("dry_run"):
        d.text((75,103),"DRY RUN",font=font(8,True),fill=0)
    url=state.get("guest_url","")
    if url:
        try:
            import qrcode
            qr=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L,
                             box_size=1,border=2)
            qr.add_data(url);qr.make(fit=True)
            bitmap=qr.make_image(fill_color="black",back_color="white").convert("1")
            if bitmap.width>68:
                LOG.warning("Guest QR needs %d modules: cannot fit",bitmap.width)
            else:
                scale=max(1,68//bitmap.width)
                bitmap=bitmap.resize((bitmap.width*scale,bitmap.height*scale),
                                     Image.Resampling.NEAREST)
                img.paste(bitmap,(178+(68-bitmap.width)//2,21))
        except (ImportError,ValueError) as exc:
            LOG.warning("QR unavailable: %s",exc)
    d.text((181,91),"WEB CODE",font=font(8,True),fill=0)
    code=str(state.get("challenge_code") or "OFF")
    if len(code)==6 and code.isdecimal():
        d.text((182,103),code,font=font(13,True),fill=0)
    else:
        d.text((184,105),"OFF",font=font(11,True),fill=0)
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
    try:
        from nfc_pairing import paired, state as pairing_state
        nfc_paired=paired()
        pair_armed=pairing_state() is not None
    except (OSError,ValueError):
        nfc_paired=False
        pair_armed=False
    return {"guest_url":guest_print_url(conf),"challenge_code":code,
            "nfc_paired":nfc_paired,"pair_armed":pair_armed,
            "activity":pet_activity(),
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
    # Event changes are sampled quickly, but physical full-screen refreshes
    # are capped to avoid constant e-paper flashing and excess wear.
    min_refresh=max(20,int(setting.get("activity_min_refresh_seconds",25)))
    logging.basicConfig(level=logging.INFO)
    if args.preview:
        render(snapshot(conf),rotation).save("/tmp/fmi-print-display.png")
        print("Saved /tmp/fmi-print-display.png")
        return
    with Epaper() as epd:
        last_frame=None
        last_refresh=0.0
        last_periodic=0.0
        while True:
            try:
                state=snapshot(conf)
                frame=render(state,rotation)
                frame_bytes=frame.tobytes()
                now=time.monotonic()
                changed=(frame_bytes!=last_frame)
                due=(last_frame is None or now-last_periodic>=delay or
                     (changed and now-last_refresh>=min_refresh))
                if due:
                    if conf.get("nfc_auto_update") and state.get("guest_url") and conf.get("nfc_i2c_bus") is not None:
                        try:
                            from nfc_tag import sync
                            sync(int(conf["nfc_i2c_bus"]),state["guest_url"],allow_write=True)
                        except Exception:
                            LOG.exception("Could not synchronize ST25DV16K guest URL")
                    epd.init()
                    epd.display(frame)
                    epd.sleep()
                    last_frame=frame_bytes
                    last_refresh=now
                    last_periodic=now
                    LOG.info("Displayed: %s",state)
            except Exception:
                LOG.exception("Display update failed")
            if args.once:break
            time.sleep(5)

if __name__=="__main__": main()
