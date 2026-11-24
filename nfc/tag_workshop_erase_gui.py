#!/usr/bin/env python3
"""Standalone PT35 NFC Type 2 NDEF eraser.

Erase means an empty NDEF TLV, not destructive whole-chip formatting.
Manufacturer/UID, CC, locking and configuration pages are never altered.
"""
import queue
import threading
import tkinter as tk
from tkinter import messagebox

from tag_workshop_ndef import tlv
from tag_workshop_rf import perform, save_backup
from tag_workshop_raw import transfer_plan


class Eraser:
    def __init__(self, root):
        self.root = root
        self.snapshot = None
        self.events = queue.Queue()
        self.busy = False
        root.title("PT35 · Erase NDEF")
        root.geometry("800x480")
        root.minsize(600, 360)
        root.configure(bg="#171c25")
        tk.Label(root, text="Erase NDEF", font=("DejaVu Sans", 21, "bold"),
                 bg="#171c25", fg="white").pack(anchor="w", padx=20, pady=(16, 9))
        tk.Label(root, text="Make a compatible Type 2 tag's NDEF data empty. "
                 "Its UID and protected configuration remain unchanged.",
                 font=("DejaVu Sans", 11), wraplength=730, justify="left",
                 bg="#171c25", fg="#c8d5e5").pack(anchor="w", padx=20)
        self.state = tk.StringVar(value="Present a tag and choose Read tag.")
        tk.Label(root, textvariable=self.state, wraplength=720, justify="left",
                 font=("DejaVu Sans", 12), bg="#171c25", fg="#6ce0d0"
                 ).pack(fill="x", padx=20, pady=18)
        self.detail = tk.StringVar(value="No tag selected")
        tk.Label(root, textvariable=self.detail, wraplength=730,
                 justify="left", font=("DejaVu Sans", 12),
                 bg="#171c25", fg="white").pack(fill="x", padx=20, pady=12)
        buttons = tk.Frame(root, bg="#171c25")
        buttons.pack(side="bottom", fill="x", padx=14, pady=16)
        self.read_btn = tk.Button(buttons, text="Read tag", command=self.read,
                                  bg="#147b85", fg="white", height=2,
                                  font=("DejaVu Sans", 12))
        self.read_btn.pack(side="left", expand=True, fill="x", padx=4)
        self.erase_btn = tk.Button(buttons, text="Erase NDEF & verify",
                                   command=self.erase, bg="#975127", fg="white",
                                   height=2, font=("DejaVu Sans", 12))
        self.erase_btn.pack(side="left", expand=True, fill="x", padx=4)
        tk.Button(buttons, text="Exit", command=self.close, bg="#29364b",
                  fg="white", height=2, font=("DejaVu Sans", 12)).pack(
                      side="left", expand=True, fill="x", padx=4)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(80, self.pump)

    def set_busy(self, value):
        self.busy = value
        self.read_btn.configure(state="disabled" if value else "normal")
        self.erase_btn.configure(state="disabled" if value else "normal")

    def run(self, fn, done):
        if self.busy:
            return
        self.set_busy(True)
        def worker():
            try:
                self.events.put((done, fn(), None))
            except Exception as exc:
                self.events.put((done, None, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def pump(self):
        try:
            while True:
                done, result, error = self.events.get_nowait()
                self.set_busy(False)
                if error:
                    self.state.set("Error: " + error)
                    messagebox.showerror("Erase NDEF", error)
                else:
                    done(result)
        except queue.Empty:
            pass
        self.root.after(80, self.pump)

    def read(self):
        self.snapshot = None
        self.state.set("Reading NFC-A Type 2 tag…")
        self.run(lambda: perform("read"), self.loaded)

    def loaded(self, result):
        self.snapshot = result
        image = tlv("Empty", "", result["capacity"])
        changes = transfer_plan(result["data"], image)
        self.detail.set(f"UID: {result['uid']} · {result['capacity']} bytes · "
                        f"{len(changes)} changed pages")
        self.state.set("Tag read. Press Erase NDEF & verify to confirm, or Exit.")

    def erase(self):
        snap = self.snapshot
        if snap is None:
            messagebox.showinfo("Erase NDEF", "Read a tag first.")
            return
        image = tlv("Empty", "", snap["capacity"])
        changes = transfer_plan(snap["data"], image)
        if not changes:
            self.state.set("Tag already has the intended empty NDEF image.")
            return
        if not messagebox.askyesno(
                "Confirm erase",
                f"Erase NDEF user data on UID {snap['uid']}?\n\n"
                f"{len(changes)} memory pages will change. A backup will be saved first.\n"
                "This does NOT modify UID, lock bits or configuration."):
            return
        try:
            backup = save_backup(snap)
        except OSError as exc:
            messagebox.showerror("Backup failed", str(exc))
            return
        self.state.set("Writing empty NDEF and verifying… Keep tag in place.")
        self.run(
            lambda: perform(
                "write", expected_uid=snap["uid"],
                expected_data=snap["data"], new_data=image,
                backup_file=backup, raw_transfer=True),
            self.done)

    def done(self, result):
        self.snapshot = result
        self.state.set(f"ERASE VERIFIED · UID {result['uid']} · "
                       f"{result['written']} page writes. Ready for another tag.")
        self.detail.set(f"UID: {result['uid']} · NDEF is empty")

    def close(self):
        if self.busy:
            self.state.set("Finish the current tag operation before closing.")
            return
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    Eraser(root)
    root.mainloop()
