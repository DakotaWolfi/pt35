#!/usr/bin/env python3
"""Safely connect the already-wired ST25DV tag on bus 0 to the guest page.

Preview does not alter tag or configuration. --apply writes and verifies the
NDEF URL first, then enables automatic URL refresh in local config.json.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess

from nfc_tag import sync

ROOT = Path(__file__).resolve().parent

def wifi_guest_url(conf):
    if conf.get("nfc_url"):
        return str(conf["nfc_url"])
    output=subprocess.check_output(["ip","-j","-4","address","show","dev","wlan0"],text=True,timeout=3)
    for iface in json.loads(output):
        for addr in iface.get("addr_info",[]):
            if addr.get("family")=="inet" and addr.get("local"):
                return "http://{}:{}/".format(addr["local"],int(conf.get("port",8767)))
    raise RuntimeError("wlan0 has no IPv4; set nfc_url explicitly in config.json")

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bus",type=int,default=0,help="Already confirmed tag I2C bus")
    p.add_argument("--apply",action="store_true",help="Write verified URL and enable automatic sync")
    args=p.parse_args()
    path=ROOT/"config.json"
    conf=json.loads(path.read_text(encoding="utf-8"))
    url=wifi_guest_url(conf)
    print("Tag I2C bus:",args.bus,"guest URL:",url)
    if not args.apply:
        sync(args.bus,url,allow_write=False)
        print("Preview only. Check the existing tag data before --apply.")
        return
    sync(args.bus,url,allow_write=True)
    # sync() verified a read-back (or found the same NDEF already present).
    conf["nfc_i2c_bus"]=args.bus
    conf["nfc_auto_update"]=True
    temporary=path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(conf,indent=2)+"\n",encoding="utf-8")
    original_stat=path.stat()
    os.chown(temporary,original_stat.st_uid,original_stat.st_gid)
    temporary.chmod(0o600)
    temporary.replace(path)
    print("NFC automatic URL sync enabled in local config.json.")
    print("Restart display: sudo systemctl restart fmi-print-display")
    print("Tap the tag with a phone on Wi-Fi to verify the browser opens the guest page.")

if __name__=="__main__":
    main()
