#!/usr/bin/env python3
"""Merge FMI tools into PocketTerm35-OS launcher without replacing stock apps."""
from pathlib import Path
import re
import shutil
import sys
from datetime import datetime

root=Path(sys.argv[1]).resolve()
home=Path.home()
config=home/".config/pt35"
config.mkdir(parents=True,exist_ok=True)
apps=config/"apps.toml"
menu=config/"menu.toml"
for path in (apps,menu):
    if path.exists():
        shutil.copy2(path,path.with_name(f"{path.name}.bak.{datetime.now():%Y%m%d-%H%M%S}"))

def section_remove(text, heading):
    pattern=rf"(?ms)^\[{re.escape(heading)}\][ \t]*\n.*?(?=^\[|\Z)"
    return re.sub(pattern,"",text)

def add_app(id,label,glyph,icon,exec_,match=None,scale=None):
    lines=[f"[app.{id}]",f'label = "{label}"',f'glyph = "{glyph}"',
           f'icon = "{icon}"',f'exec = "{exec_}"']
    if match:
        if match == "PT35NFC":
            lines.append('match = { class = "PT35NFC" }')
        else:
            lines.append(f'match = {{ app_id = "{match}" }}')
    if scale:
        lines.append(f"scale = {scale}")
    return "\n".join(lines)+"\n"

bin=home/".local/bin/fmi-pt35-tool"
s=apps.read_text() if apps.exists() else ""
for id in ("fmi_spectrum","fmi_nfc","fmi_battery","fmi_remote_eye","fmi_dashboard","fmi_trainer","fmi_nfc_legacy","fmi_nfc_experimental"):
    s=section_remove(s,f"app.{id}")
entries=[
  ("fmi_spectrum","Spectral analyser","SP","utilities-system-monitor",f"foot -a fmi-spectrum {bin} spectrum","fmi-spectrum",None),
  ("fmi_nfc","PT35 NFC Reader","NF","network-wireless",str(home/".local/bin/pt35-nfc-gui"),None,None),
  ("fmi_battery","Battery diagnostics","BT","battery",f"foot --hold -a fmi-battery {bin} battery","fmi-battery",None)]
# Prefer the genuine recovered Pi4 GUIs when their wrappers are installed.
original_nfc = home/".local/bin/pt35-nfc-gui"
original_spectrum = home/".local/bin/pt35-original-spectrum"
if original_nfc.is_file():
    entries = [
        (id, "PT35 NFC Reader", glyph, icon, str(original_nfc), None, None)
        if id == "fmi_nfc" else (id,label,glyph,icon,cmd,match,scale)
        for id,label,glyph,icon,cmd,match,scale in entries
    ]
if original_spectrum.is_file():
    entries = [
        (id, "Spectrum (original)", glyph, icon, str(original_spectrum), None, None)
        if id == "fmi_spectrum" else (id,label,glyph,icon,cmd,match,scale)
        for id,label,glyph,icon,cmd,match,scale in entries
    ]
for id, label, glyph, icon, cmd, match, scale in entries:
    s=s.rstrip()+"\n\n"+add_app(id,label,glyph,icon,cmd,match,scale)
extra=[
 ("fmi_remote_eye","Remote Eye","RE","camera-web",home/".local/bin/pt35-eye-control"),
 ("fmi_dashboard","Collar Pet dashboard","CP","utilities-system-monitor",home/".local/bin/cp-dashboard"),
 ("fmi_trainer","Petmind training","PT","applications-education",home/".local/bin/cp-petmind-training")]
installed_extra=[]
log_wrappers = {
 "fmi_remote_eye": home/".local/bin/pt35-run-eye",
 "fmi_dashboard": home/".local/bin/pt35-run-collarpet",
 "fmi_trainer": home/".local/bin/pt35-run-trainer",
}
for id,label,glyph,icon,executable in extra:
    if executable.is_file():
        effective=log_wrappers.get(id)
        cmd=effective if effective is not None and effective.is_file() else executable
        if id == "fmi_remote_eye":
            # Original controller is CLI-only and requires one explicit action.
            cmd = str(cmd) + " --button"
        s=s.rstrip()+"\n\n"+add_app(id,label,glyph,icon,str(cmd))
        installed_extra.append((id,label))
# Delay writing both configurations until TOML validation succeeds.

icon= root/"tools/pt35_menu_icon.py"
toggle1=f"python3 {icon} wolf"
toggle2=f"python3 {icon} bars"

# The system settings page is overridden wholesale if user supplies it.
# Preserve user additions if any; otherwise take the default page from system.
m=menu.read_text() if menu.exists() else ""
if not re.search(r"(?m)^\[menu.settings\][ \t]*$",m):
    system=Path("/usr/share/pt35-desktop/pt35/menu.toml")
    defaults=system.read_text() if system.exists() else ""
    found=re.search(r"(?ms)^\[menu.settings\][ \t]*\n.*?(?=^\[|\Z)",defaults)
    if not found:
        raise SystemExit("Cannot read stock Settings menu; no changes made to menu.toml")
    m=m.rstrip()+"\n\n"+found.group(0).strip()+"\n"

# Our own section goes at the start of settings while leaving defaults alone.
prefix="# FMI_START"
suffix="# FMI_END"
m=re.sub(r"(?ms)^[ \t]*# FMI_START\n.*?^[ \t]*# FMI_END\n?","",m)
m=re.sub(r"(?m)^(\[menu.settings\][ \t]*\n[\s\S]*?^[ \t]*entries\s*=\s*\[)",
         lambda hit: hit.group(1)+f'''
  {prefix}
  {{ label = "PT35 customization", goto = "fmi_settings", icon = "preferences-desktop-appearance", glyph = "PT" }},
  {suffix}''',m,count=1)
m=section_remove(m,"menu.fmi")
m=section_remove(m,"menu.fmi_leds")
m=section_remove(m,"menu.fmi_settings")
fmi=[
 (('"Spectrum (original)"' if original_spectrum.is_file() else '"Spectral analyser"') + ', app = "fmi_spectrum", icon = "utilities-system-monitor"'),
 ('"PT35 NFC Reader", app = "fmi_nfc", icon = "network-wireless"'),
 ('"Battery diagnostics", app = "fmi_battery", icon = "battery"')]
fmi += [(f'"{label}", app = "{id}", glyph = "{label[:2]}"') for id,label in installed_extra]
m=m.rstrip()+"\n\n[menu.fmi]\ntitle = \"FMI Tools\"\nentries = [\n"
m+="".join(f"  {{ label = {item} }},\n" for item in fmi)
m+="  { label = \"LED Controls\", goto = \"fmi_leds\", glyph = \"LED\" },\n]\n"
m+="""\n[menu.fmi_leds]
title = "PT35 LEDs"
entries = [
"""
led=home/".local/bin/pt35-ledctl"
for label,args in (("LEDs off","off"),("Idle glow","idle"),("Rainbow","rainbow"),("Battery bar","battery"),("White flash","flash 40 40 40")):
    m+=f'  {{ label = "{label}", exec = "{led} {args}", glyph = "LED" }},\n'
m+="]\n"
m+=f"""
[menu.fmi_settings]
title = "PT35 customization"
entries = [
  {{ label = "Wolf menu icon", exec = "{toggle1}", icon = "face-smile", glyph = "WF" }},
  {{ label = "Normal menu icon", exec = "{toggle2}", icon = "open-menu", glyph = "MN" }},
]
"""
try:
    import tomllib
    tomllib.loads(m)
    tomllib.loads(s)
except Exception as ex:
    raise SystemExit(f"ERROR: Generated TOML rejected, no config overwritten: {ex}")
apps.write_text(s)
menu.write_text(m)
print("FMI Tools tile and Settings > PT35 customization added, with LED controls.")
print("Apps: spectrum, NFC, battery"+(" plus "+", ".join(name for _,name in installed_extra) if installed_extra else ""))
print("Stock navigation remains intact. Wolf option needs the patched taskbar installed.")
