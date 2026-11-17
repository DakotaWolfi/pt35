#!/usr/bin/env python3
"""FMI Print Pet offline NFC remote — PT35 keyboard/mouse-friendly 800x480 GUI.

Calls the proven ST25R3916 CLI in a subprocess. Only one RF request may be
active at a time; this avoids collisions with the PT35 NFC scanner. No Wi-Fi.
"""
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageOps, ImageTk
from pathlib import Path as _Path
sys.path.insert(0,str(_Path(__file__).resolve().parents[1]/"print_station"))
from mailbox_protocol import pack

HERE=Path(__file__).resolve().parent
CLI=HERE/"print_pet_mailbox.py"
DEFAULT_UID=os.environ.get("PRINT_PET_UID","E00226003269825F").upper()
UID_RE=re.compile(r"^[0-9A-F]{16}$")

class PrintPetApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PT35 Print Pet")
        self.geometry("800x480")
        self.minsize(640,400)
        self.configure(bg="#111923")
        self.uid=tk.StringVar(value=DEFAULT_UID)
        self.code=tk.StringVar()
        self.name=tk.StringVar(value="PT35")
        self.message=tk.StringVar(value="AWOO from PT35!")
        self.image_path=tk.StringVar()
        self.state=tk.StringVar(value="Ready — hold PT35 near Print Pet")
        self.report=tk.StringVar(value="Printer: unknown | Queue: — | Printed: —")
        self.events=queue.Queue()
        self.busy=False
        self.current=None
        self._photo=None
        self._build()
        self.after(100,self._poll)
        self.bind("<Escape>",lambda e:self.destroy())
        self.protocol("WM_DELETE_WINDOW",self._close)

    def _build(self):
        notebook=ttk.Notebook(self)
        notebook.pack(fill="both",expand=True,padx=10,pady=(8,0))
        status=ttk.Frame(notebook,padding=12)
        tickets=ttk.Frame(notebook,padding=12)
        pictures=ttk.Frame(notebook,padding=12)
        notebook.add(status,text="Status")
        notebook.add(tickets,text="Text receipt")
        notebook.add(pictures,text="Picture")
        for tab in (status,tickets,pictures):
            tab.columnconfigure(1,weight=1)

        ttk.Label(status,text="Print Pet NFC UID").grid(row=0,column=0,sticky="w",pady=5)
        ttk.Entry(status,textvariable=self.uid,width=25).grid(row=0,column=1,sticky="ew",pady=5)
        ttk.Label(status,textvariable=self.report,font=("DejaVu Sans",13)).grid(row=1,column=0,columnspan=2,sticky="w",pady=20)
        ttk.Button(status,text="Read NFC status",command=lambda:self._run("status")).grid(row=2,column=0,columnspan=2,sticky="ew",pady=6)
        ttk.Label(status,text="No Wi-Fi required. Hold the NFC antennas aligned until the reply arrives.").grid(row=3,column=0,columnspan=2,sticky="w",pady=10)

        ttk.Label(tickets,text="Recipient / name").grid(row=0,column=0,sticky="w",pady=5)
        ttk.Entry(tickets,textvariable=self.name).grid(row=0,column=1,sticky="ew",pady=5)
        ttk.Label(tickets,text="Receipt message").grid(row=1,column=0,sticky="w",pady=5)
        ttk.Entry(tickets,textvariable=self.message).grid(row=1,column=1,sticky="ew",pady=5)
        ttk.Label(tickets,text="Six-digit code on Print Pet").grid(row=2,column=0,sticky="w",pady=5)
        ttk.Entry(tickets,textvariable=self.code,width=12).grid(row=2,column=1,sticky="w",pady=5)
        ttk.Button(tickets,text="Print text over NFC",command=lambda:self._run("print")).grid(row=3,column=0,columnspan=2,sticky="ew",pady=12)

        ttk.Label(pictures,text="Photo / image").grid(row=0,column=0,sticky="w",pady=5)
        ttk.Entry(pictures,textvariable=self.image_path).grid(row=0,column=1,sticky="ew",pady=5)
        ttk.Button(pictures,text="Browse image…",command=self._choose_image).grid(row=1,column=0,columnspan=2,sticky="ew",pady=5)
        self.preview=ttk.Label(pictures,text="Choose a picture to preview it",anchor="center")
        self.preview.grid(row=2,column=0,columnspan=2,sticky="nsew",pady=8)
        pictures.rowconfigure(2,weight=1)
        ttk.Label(pictures,text="NFC sends a small 160×120 monochrome PNG in chunks.").grid(row=3,column=0,columnspan=2,sticky="w")
        ttk.Button(pictures,text="Print picture over NFC",command=lambda:self._run("image")).grid(row=4,column=0,columnspan=2,sticky="ew",pady=7)

        footer=ttk.Frame(self,padding=(10,5))
        footer.pack(fill="x")
        ttk.Label(footer,textvariable=self.state).pack(side="left",fill="x",expand=True)
        ttk.Button(footer,text="Close",command=self._close).pack(side="right")
        log_frame=ttk.Frame(self,padding=(10,0,10,8))
        log_frame.pack(fill="x")
        self.log=tk.Text(log_frame,height=4,wrap="word",font=("DejaVu Sans Mono",9))
        self.log.pack(fill="x")
        self.log.configure(state="disabled")

    def _choose_image(self):
        file=filedialog.askopenfilename(parent=self,
            filetypes=[("Images","*.png *.jpg *.jpeg *.bmp *.webp"),("All files","*")])
        if not file:return
        self.image_path.set(file)
        try:
            with Image.open(file) as im:
                im=ImageOps.exif_transpose(im)
                im.thumbnail((320,100))
                self._photo=ImageTk.PhotoImage(im.convert("RGB"))
            self.preview.configure(image=self._photo,text="")
        except (OSError,ValueError) as exc:
            self.preview.configure(image="",text=str(exc))

    def _append(self,line):
        self.log.configure(state="normal")
        self.log.insert("end",line.rstrip()+"\n")
        self.log.see("end")
        if int(self.log.index("end-1c").split(".")[0])>150:
            self.log.delete("1.0","51.0")
        self.log.configure(state="disabled")

    def _run(self,action):
        if self.busy:return
        uid=self.uid.get().strip().upper()
        if not UID_RE.fullmatch(uid):
            messagebox.showerror("Invalid UID","Expected 16 hex digits for the external Print Pet tag",parent=self)
            return
        cmd=[sys.executable,"-u",str(CLI),action,"--uid",uid]
        if action in ("print","image"):
            code=self.code.get().strip()
            if not re.fullmatch(r"[0-9]{6}",code):
                messagebox.showerror("Print code","Enter the six-digit code displayed on Print Pet",parent=self)
                return
            if action=="print":
                name=self.name.get().strip()
                msg=self.message.get().strip()
                if not name or not msg or len(name)>40 or len(msg)>40 or not(name+msg).isascii():
                    messagebox.showerror("Text receipt","Use short ASCII fields (1–40 characters)",parent=self)
                    return
                try:
                    pack("print","00000000",name=name,message=msg,code=code)
                except ValueError as exc:
                    messagebox.showerror("NFC receipt limit",str(exc)+"; use a shorter message.",parent=self)
                    return
                cmd.extend(["--name",name,"--message",msg])
            else:
                photo=Path(self.image_path.get()).expanduser()
                if not photo.is_file():
                    messagebox.showerror("Picture","Choose an existing image file first",parent=self)
                    return
                cmd.extend(["--image",str(photo)])
            if not messagebox.askyesno("Confirm NFC print",
                "Send this print job to Print Pet over NFC?\nKeep the antennas aligned until acknowledged.",parent=self):
                return
            cmd.extend(["--code",code,"--confirm"])
        self.busy=True
        self.state.set("Communicating over NFC…")
        def work():
            try:
                proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                      text=True,bufsize=1)
                lines=[]
                for line in proc.stdout:
                    lines.append(line)
                    self.events.put(("line",line))
                rc=proc.wait()
                self.events.put(("exit",rc))
            except OSError as exc:
                self.events.put(("line",str(exc)))
                self.events.put(("exit",-1))
        threading.Thread(target=work,daemon=True).start()

    def _poll(self):
        try:
            while True:
                event=self.events.get_nowait()
                if event[0]=="line":
                    line=event[1]
                    if line.strip():
                        self._append(line)
                    if line.startswith("Image NFC "):
                        self.state.set(line.strip())
                    if line.startswith("Print Pet:"):
                        try:
                            import ast
                            status=ast.literal_eval(line.split("Print Pet:",1)[1].strip())
                            if isinstance(status,dict):
                                if "ready" in status:
                                    self.report.set("Printer: "+("ready" if status.get("ready") else "offline")
                                                    +" | Printing: "+str(bool(status.get("printing")))
                                                    +" | Queue: "+str(status.get("queue","—"))
                                                    +" | Printed: "+str(status.get("printed","—")))
                                elif status.get("ok"):
                                    self.state.set(str(status.get("message","Accepted by Print Pet")))
                        except (ValueError,SyntaxError):pass
                elif event[0]=="exit":
                    self.busy=False
                    if event[1]:
                        self.state.set("NFC error — see log")
                    elif not self.state.get().startswith("Image queued"):
                        self.state.set("Completed")
        except queue.Empty:
            pass
        self.after(100,self._poll)

    def _close(self):
        if self.busy:
            messagebox.showinfo("NFC transfer active",
                                "An NFC exchange is in progress. Finish it before closing.",parent=self)
            return
        self.destroy()

if __name__=="__main__":
    PrintPetApp().mainloop()
