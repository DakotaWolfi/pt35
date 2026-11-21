#!/usr/bin/env python3
"""Add visible EXIT control to the already-recovered dark PetMind trainer.

Minimal, reversible edit. Leaves all recording and transport code intact.
"""
from pathlib import Path
from datetime import datetime
import ast
import shutil
p=Path.home()/".local/bin/cp-petmind-training"
if not p.is_file():
    raise SystemExit(f"Missing PetMind trainer: {p}")
s=p.read_text(encoding="utf-8")
if "# PT35_PI5_PETMIND_DARK_V1" not in s:
    raise SystemExit("Only supports the confirmed PT35 dark UI. Install it first.")
marker="# PT35_PI5_PETMIND_EXIT_V1"
if marker in s:
    print("Exit button already present.")
    raise SystemExit(0)
anchor='label(head,"LINK",10,True,MUTED,BG).pack(side="right",padx=6)'
if s.count(anchor)!=1:
    raise SystemExit("PetMind header changed; refusing uncertain patch")
s=s.replace(anchor,
    'btn(head,"✕ EXIT",quit_app,fg="#ffffff",bg="#82364b").pack(side="right",padx=(6,10))\n'
    +marker+'\n'+anchor,1)
ast.parse(s,filename=str(p))
back=p.with_name(p.name+f".before-exit-{datetime.now():%Y%m%d-%H%M%S}.bak")
shutil.copy2(p,back)
p.write_text(s,encoding="utf-8")
print(f"Exit button added. Backup: {back}")
