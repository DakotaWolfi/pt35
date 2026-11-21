#!/usr/bin/env python3
"""Re-skin the EXACT transferred Pi4 PetMind application for the 800x480 PT35.
The transport/SSH/BLE/recording backend before the UI anchor is retained.
A dated backup is made. Idempotent; refuses unrecognized source structure.
"""
from pathlib import Path
import ast
import shutil
from datetime import datetime

app = Path.home()/".local/bin/cp-petmind-training"
mark = "# PT35_PI5_PETMIND_DARK_V1"
if not app.is_file() or app.is_symlink():
    raise SystemExit(f"Original trainer missing or symlink: {app}")
s = app.read_text(encoding="utf-8")
if mark in s:
    print("PetMind dark UI already installed.")
    raise SystemExit(0)
start = "top=tk.Frame(root);top.pack("
end = 'transport.trace_add("write",'
if s.count(start) != 1 or s.count(end) != 1:
    raise SystemExit("Unknown trainer UI layout; no changes made.")
begin = s.index(start)
finish = s.index(end,begin)
replacement = '''
# PT35_PI5_PETMIND_DARK_V1
# All original backend functions above this line are preserved.
BG="#0c121b"; PANEL="#182432"; CARD="#202f42"; FG="#e9f1fd"
MUTED="#a2b6cb"; BLUE="#57c9f8"; GREEN="#4cdda6"; RED="#ff7387"
AMBER="#ffc26d"
root.configure(bg=BG)
root.geometry("800x480")
root.minsize(640,400)
root.attributes("-fullscreen",True)
root.bind("<Escape>", lambda e: root.attributes("-fullscreen",False))
root.bind("<F11>", lambda e: root.attributes("-fullscreen",not root.attributes("-fullscreen")))
def quit_app(_=None):
    root.destroy()
    return "break"
def start_button(_=None):
    if not command_busy:
        background(["start"])
    return "break"
# Custom PT35 gamepad bridge maps A=>F18, B=>F17.
root.bind("<F18>",start_button,add="+")
root.bind("<F17>",quit_app,add="+")
root.protocol("WM_DELETE_WINDOW",quit_app)

style=ttk.Style(root)
style.theme_use("clam")
style.configure("PT.TNotebook",background=BG,borderwidth=0)
style.configure("PT.TNotebook.Tab",background=CARD,foreground=FG,
                padding=(14,7),font=("DejaVu Sans",11,"bold"))
style.map("PT.TNotebook.Tab",background=[("selected", "#31506c")],
          foreground=[("selected", "#ffffff")])
style.configure("PT.TCombobox",fieldbackground=CARD,background=CARD,foreground=FG)
style.map("PT.TCombobox",fieldbackground=[("readonly",CARD)],
          foreground=[("readonly",FG)])

def label(parent,txt="",size=11,bold=False,fg=FG,bg=None,**kwargs):
    return tk.Label(parent,text=txt,fg=fg,bg=bg or PANEL,
                    font=("DejaVu Sans",size,"bold" if bold else "normal"),**kwargs)
def btn(parent,txt,fn,fg=FG,bg=CARD):
    return tk.Button(parent,text=txt,command=fn,bg=bg,fg=fg,
                     activebackground="#385574",activeforeground="#ffffff",
                     relief="flat",bd=0,padx=7,pady=8,
                     font=("DejaVu Sans",10,"bold"),takefocus=True)

head=tk.Frame(root,bg=BG)
head.pack(fill="x",padx=12,pady=(8,4))
label(head,"PETMIND",19,True,BLUE,BG).pack(side="left")
label(head,"TRAINING RECORDER",12,True,MUTED,BG).pack(side="left",padx=(10,0))
ttk.Combobox(head,textvariable=transport,values=["AUTO","Wi-Fi","BLE"],
             state="readonly",width=8,style="PT.TCombobox").pack(side="right")
label(head,"LINK",10,True,MUTED,BG).pack(side="right",padx=6)

# Recorder status remains visible across all tabs.
status=tk.Frame(root,bg=PANEL,padx=10,pady=6)
status.pack(fill="x",padx=12,pady=(0,5))
rec_var=tk.StringVar(value="■ STOPPED")
label_var=tk.StringVar(value="—")
frames_var=tk.StringVar(value="—")
file_var=tk.StringVar(value="—")
link_var=tk.StringVar(value="CHECKING…")
last_action_var=tk.StringVar(value="Ready")
def stat(parent,col,title,var):
    frame=tk.Frame(parent,bg=PANEL)
    frame.grid(row=0,column=col,sticky="ew",padx=(0,8))
    label(frame,title,9,True,MUTED).pack(anchor="w")
    value=tk.Label(frame,textvariable=var,bg=PANEL,fg=FG,
                   anchor="w",font=("DejaVu Sans",11,"bold"))
    value.pack(fill="x")
    return value
for i in range(4): status.grid_columnconfigure(i,weight=1)
rec_value=stat(status,0,"RECORDER",rec_var)
link_value=stat(status,1,"LINK",link_var)
stat(status,2,"LABEL",label_var)
stat(status,3,"FRAMES",frames_var)
message=tk.Frame(root,bg=BG)
message.pack(fill="x",padx=14)
tk.Label(message,textvariable=last_action_var,fg=MUTED,bg=BG,
         anchor="w",font=("DejaVu Sans",10),height=1).pack(fill="x")

tabs=ttk.Notebook(root,style="PT.TNotebook")
tabs.pack(fill="both",expand=True,padx=10,pady=(1,6))
def tab(name):
    frame=tk.Frame(tabs,bg=PANEL)
    tabs.add(frame,text=name)
    return frame

rec_tab=tab("RECORD")
row=tk.Frame(rec_tab,bg=PANEL)
row.pack(fill="x",padx=8,pady=(12,8))
for i,(title,args,color) in enumerate((
    ("START",["start"],"#176b52"),
    ("STOP",["stop"],"#8a3243"),
    ("STATUS",["status"],CARD),
    ("CLEAR LABEL",["clear"],CARD))):
    row.grid_columnconfigure(i,weight=1)
    btn(row,title,lambda a=args:background(a),bg=color).grid(
        row=0,column=i,sticky="ew",padx=3)
duration_row=tk.Frame(rec_tab,bg=PANEL)
duration_row.pack(fill="x",padx=13,pady=5)
label(duration_row,"Label duration (seconds)",11,True,MUTED).pack(side="left")
tk.Spinbox(duration_row,from_=5,to=255,textvariable=duration,width=6,
           bg=CARD,fg=FG,insertbackground=FG,buttonbackground=CARD,
           relief="flat",font=("DejaVu Sans",12)).pack(side="left",padx=12)
label(rec_tab,"A = START   •   B = EXIT   •   X/Y = navigation",
      10,False,MUTED).pack(anchor="w",padx=13,pady=10)

labels_tab=tab("LABELS")
label(labels_tab,"Choose a context label",11,True,BLUE).pack(anchor="w",padx=11,pady=(7,2))
choices=["quiet","resting","speech","music","walking","crowd","machinery",
         "dark_active","ef_badges","fox","riding","outdoor","other"]
label_grid=tk.Frame(labels_tab,bg=PANEL)
label_grid.pack(fill="both",expand=True,padx=8,pady=(2,8))
for c in range(4): label_grid.columnconfigure(c,weight=1)
for i,n in enumerate(choices):
    btn(label_grid,n.replace("_"," ").upper(),
        lambda x=n:background(["label",x,str(duration.get())])).grid(
            row=i//4,column=i%4,sticky="nsew",padx=3,pady=3)

events_tab=tab("EVENTS")
label(events_tab,"Instant event marker",11,True,BLUE).pack(anchor="w",padx=11,pady=(8,4))
event_grid=tk.Frame(events_tab,bg=PANEL)
event_grid.pack(fill="x",padx=8)
for c in range(3): event_grid.columnconfigure(c,weight=1)
for i,n in enumerate(["bang","clap","surprise","unexpected_noise","fox_appeared"]):
    btn(event_grid,n.replace("_"," ").upper(),
        lambda x=n:background(["event",x])).grid(
            row=i//3,column=i%3,sticky="ew",padx=3,pady=5)

res_tab=tab("RECOVERY")
label(res_tab,"Collar Pet recovery access point",12,True,BLUE).pack(
    anchor="w",padx=13,pady=(13,8))
btn(res_tab,"START RESCUE AP",lambda:rescue("start")).pack(
    fill="x",padx=13,pady=4)
btn(res_tab,"STOP RESCUE AP",lambda:rescue("stop")).pack(
    fill="x",padx=13,pady=4)

# Full file name available on demand; don't truncate the status row.
file_row=tk.Frame(rec_tab,bg=PANEL)
file_row.pack(fill="x",padx=12,pady=(4,0))
label(file_row,"FILE:",10,True,MUTED).pack(side="left")
tk.Label(file_row,textvariable=file_var,bg=PANEL,fg=FG,
         anchor="w",font=("DejaVu Sans",10)).pack(side="left",padx=8)
'''
new = s[:begin] + replacement + "\n" + s[finish:]
ast.parse(new, str(app))
backup=app.with_name(f"{app.name}.before-dark-{datetime.now():%Y%m%d-%H%M%S}.bak")
shutil.copy2(app,backup)
app.write_text(new,encoding="utf-8")
print(f"Installed PT35 dark tabbed PetMind UI. Backup: {backup}")
print("Recording/SSH/BLE functions preserved; A starts recording, B exits.")
