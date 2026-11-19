#!/usr/bin/env python3
"""Repair Café electrical tester report -> draft ESC/POS receipt.

Protocol adapters will populate the JSON report once the tester model is known.
This module does not measure or certify electrical safety.
"""
import argparse
import json
from pathlib import Path
import socket
import sys
import unicodedata

MAX_REPORT_BYTES=65536
MAX_MEASUREMENTS=40


def ascii_text(value, length=70):
    value=unicodedata.normalize("NFKD",str(value))
    return "".join(ch for ch in value if ord(ch)<128 and ch not in "\r\x1b\x7f")[:length]


def validate_report(data):
    if not isinstance(data,dict):
        raise ValueError("Report must be a JSON object")
    required=("device","tester","date","result")
    if any(not str(data.get(k,"")).strip() for k in required):
        raise ValueError("Missing device, tester, date or original result")
    result=str(data["result"]).upper().strip()
    if result not in ("PASS","FAIL","INCOMPLETE","UNKNOWN"):
        raise ValueError("Result must be copied as PASS, FAIL, INCOMPLETE, or UNKNOWN")
    tests=data.get("measurements",[])
    if not isinstance(tests,list) or len(tests)>MAX_MEASUREMENTS:
        raise ValueError("Too many measurements")
    for test in tests:
        if not isinstance(test,dict) or not str(test.get("name","")).strip():
            raise ValueError("Each measurement needs a name")
    return data


def format_receipt(data):
    """Return printable ASCII. The stated result is never inferred from values."""
    data=validate_report(data)
    lines=[
        "REPAIR CAFE - DEVICE TEST",
        "================================",
        "Device: "+ascii_text(data["device"],48),
    ]
    for key,caption in (("device_id","ID"),("protection_class","Class"),
                        ("serial","Device S/N"),("standard","Test standard")):
        if data.get(key):
            lines.append(caption+": "+ascii_text(data[key],50))
    lines.extend(("Date: "+ascii_text(data["date"],40),
                  "Tester: "+ascii_text(data["tester"],55)))
    if data.get("tester_serial"):
        lines.append("Tester S/N: "+ascii_text(data["tester_serial"],48))
    lines.extend(("--------------------------------","MEASUREMENTS"))
    for test in data.get("measurements",[]):
        label=ascii_text(test["name"],45)
        reading=ascii_text(test.get("value","--"),22)
        unit=ascii_text(test.get("unit",""),10)
        lines.append(label)
        lines.append("  "+reading+(" "+unit if unit else ""))
        if test.get("limit"):
            lines.append("  Limit: "+ascii_text(test["limit"],45))
        if test.get("result"):
            lines.append("  Device report: "+ascii_text(test["result"],20))
    lines.extend(("--------------------------------",
                  "TESTER RESULT: "+ascii_text(data["result"].upper(),20),
                  "--------------------------------",
                  "Copied from supplied tester record.",
                  "Not a standalone certificate.",
                  "Review and approve per local process."))
    if data.get("operator"):
        lines.append("Operator: "+ascii_text(data["operator"],50))
    lines.append("")
    return "\n".join(lines)+"\n"


def read_report(path):
    raw=Path(path).read_bytes()
    if len(raw)>MAX_REPORT_BYTES:
        raise ValueError("Input report too large")
    return validate_report(json.loads(raw.decode("utf-8")))


def print_escpos(text,host,port,timeout=8):
    """Only called after explicit --print; no retries after interrupted transfer."""
    payload=b"\x1b@" + text.encode("ascii","replace") + b"\n\n\x1dV\x01"
    with socket.create_connection((host,port),timeout=timeout) as conn:
        conn.settimeout(timeout)
        conn.sendall(payload)


def main(argv=None):
    parser=argparse.ArgumentParser(description="Review and print an imported electrical tester record")
    parser.add_argument("--input",required=True,help="JSON report supplied by a future tester adapter")
    parser.add_argument("--print",action="store_true",dest="send",help="Actually send to Epson (default: preview only)")
    parser.add_argument("--printer-host",help="Printer IP, required with --print")
    parser.add_argument("--printer-port",type=int,default=9100)
    args=parser.parse_args(argv)
    try:
        text=format_receipt(read_report(args.input))
        print(text)
        if args.send:
            if not args.printer_host or not 1<=args.printer_port<=65535:
                parser.error("--print requires --printer-host and a valid port")
            print_escpos(text,args.printer_host,args.printer_port)
            print("Sent to printer; physical completion not confirmed.",file=sys.stderr)
        else:
            print("PREVIEW ONLY (no paper used)",file=sys.stderr)
    except (OSError,ValueError,json.JSONDecodeError) as exc:
        parser.exit(1,"Report/print failed: "+str(exc)+"\n")


if __name__=="__main__":
    main()
