#!/usr/bin/env python3
"""PT35 Tag Workshop: editable NFC Type 2 NDEF text/URL/empty tags.

Experimental write mode must be explicitly enabled. Never changes a UID or
lock/configuration bits. NFC-B smart cards and ISO15693 remain read-only here.
"""
import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path

from tag_workshop_ndef import parse, tlv, plan
from tag_workshop_rf import perform, save_backup


class Workshop:
    def __init__(self, root):
        self.root = root
        self.root.title("PT35 · NFC Tag Workshop")
        self.root.geometry("800x480")
        self.root.minsize(600, 400)
        self.root.configure(bg="#171c25")
        self.events = queue.Queue()
        self.snapshot = None
        self.backup = None
        self.busy = False
        self.kind = tk.StringVar(value="Text")
        self.uid = tk.StringVar(value="No tag scanned")
        self.status = tk.StringVar(value="Ready · close NFC Reader before using Workshop")
        self.detail = tk.StringVar(value="Reads NFC-A Type 2 stickers. NFC-B and NFC-V writing: not supported yet.")
        self.write_enabled = os.getenv("PT35_TAG_WORKSHOP_WRITE") == "YES"

        top = tk.Frame(root, bg="#171c25")
        top.pack(fill="x", padx=12, pady=8)
        tk.Label(top, text="NFC Tag Workshop", fg="#d9edff", bg="#171c25",
                 font=("DejaVu Sans", 18, "bold")).pack(side="left")
        tk.Button(top, text="Exit", command=root.destroy, font=("DejaVu Sans", 12),
                  bg="#29364b", fg="white").pack(side="right")
        tk.Label(root, textvariable=self.status, fg="#56cbbf", bg="#171c25",
                 wraplength=750, anchor="w", justify="left",
                 font=("DejaVu Sans", 11)).pack(fill="x", padx=12)
        tk.Label(root, textvariable=self.uid, fg="white", bg="#171c25",
                 font=("DejaVu Sans Mono", 13), anchor="w").pack(fill="x", padx=12, pady=3)
        tk.Label(root, textvariable=self.detail, fg="#c1cad6", bg="#171c25",
                 wraplength=750, justify="left", anchor="w").pack(fill="x", padx=12)

        row = tk.Frame(root, bg="#171c25")
        row.pack(fill="x", padx=12, pady=(9, 4))
        tk.Label(row, text="NDEF type", bg="#171c25", fg="white").pack(side="left")
        selector = ttk.Combobox(row, textvariable=self.kind, values=["Text", "URL", "Empty"],
                                state="readonly", width=12)
        selector.pack(side="left", padx=10)
        selector.bind("<<ComboboxSelected>>", lambda _: self.preview())
        tk.Label(row, text="Content", bg="#171c25", fg="white").pack(side="left", padx=9)

        self.edit = tk.Text(root, height=5, font=("DejaVu Sans", 12), wrap="word",
                            bg="#252f3c", fg="white", insertbackground="white",
                            undo=True)
        self.edit.pack(fill="both", expand=True, padx=12, pady=3)
        self.edit.bind("<KeyRelease>", lambda _: self.preview())

        self.preview_var = tk.StringVar(value="No tag loaded")
        tk.Label(root, textvariable=self.preview_var, bg="#171c25", fg="#c1cad6",
                 wraplength=750, justify="left", anchor="w").pack(fill="x", padx=12, pady=3)
        commands = tk.Frame(root, bg="#171c25")
        commands.pack(fill="x", padx=10, pady=8)
        self.buttons = []
        for text, action, color in [
            ("Read tag", self.read, "#147b85"),
            ("Preview", self.preview, "#29364b"),
            ("Save backup", self.save, "#29364b"),
            ("Write & verify", self.write, "#315e3c"),
        ]:
            button = tk.Button(commands, text=text, command=action, bg=color, fg="white",
                               font=("DejaVu Sans", 11, "bold"), height=2)
            button.pack(side="left", fill="x", expand=True, padx=3)
            self.buttons.append(button)
        self.root.bind("<Escape>", lambda _: self.root.destroy() if not self.busy else None)
        self.root.after(100, self.poll)

    def content(self):
        return self.edit.get("1.0", "end-1c")

    def set_busy(self, value):
        self.busy = value
        for button in self.buttons:
            button.config(state="disabled" if value else "normal")

    def execute(self, job, done):
        if self.busy:
            return
        self.set_busy(True)
        def worker():
            try:
                result = job()
                self.events.put((done, result, None))
            except Exception as error:
                self.events.put((done, None, str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            while True:
                done, value, error = self.events.get_nowait()
                self.set_busy(False)
                if error:
                    self.status.set("Error: " + error)
                    messagebox.showerror("NFC Workshop", error)
                else:
                    done(value)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def read(self):
        self.status.set("Scanning for one NFC-A Type 2 tag…")
        self.execute(lambda: perform("read"), self.loaded)

    def loaded(self, snapshot):
        self.snapshot = snapshot
        self.backup = None
        self.uid.set("UID: " + snapshot["uid"])
        self.detail.set(f"Type 2 · {snapshot['capacity']} bytes · CC {snapshot['cc']} · "
                        "UID/lock pages protected by workshop")
        try:
            kind, value = parse(snapshot["data"])
            self.kind.set(kind)
            self.edit.delete("1.0", "end")
            self.edit.insert("1.0", value)
            self.status.set("Read complete · edit content then preview")
        except ValueError as exc:
            self.kind.set("Text")
            self.edit.delete("1.0", "end")
            self.status.set("Read complete · unsupported existing data; writing disabled: " + str(exc))
        self.preview()

    def preview(self):
        if not self.snapshot:
            self.preview_var.set("Read a Type 2 tag first")
            return
        try:
            diff = plan(self.snapshot["data"], self.kind.get(), self.content())
            image = tlv(self.kind.get(), self.content(), self.snapshot["capacity"])
            self.preview_var.set(f"{len(diff)} changed pages · {len(image)} bytes of "
                                 f"{self.snapshot['capacity']} available · UID unchanged")
        except ValueError as exc:
            self.preview_var.set("Cannot write: " + str(exc))

    def save(self):
        if not self.snapshot:
            messagebox.showinfo("Backup", "Read a tag first.")
            return
        try:
            self.backup = save_backup(self.snapshot)
            self.status.set("Saved original tag image: " + str(self.backup))
        except OSError as exc:
            messagebox.showerror("Backup", str(exc))

    def write(self):
        if not self.snapshot:
            messagebox.showinfo("Write", "Read a tag first.")
            return
        if not self.write_enabled:
            messagebox.showinfo(
                "Experimental writing disabled",
                "Read/edit/preview/backup work normally. To enable actual writes, "
                "start the Workshop with PT35_TAG_WORKSHOP_WRITE=YES. "
                "Only test on inexpensive tags you own.")
            return
        try:
            changes = plan(self.snapshot["data"], self.kind.get(), self.content())
            image = tlv(self.kind.get(), self.content(), self.snapshot["capacity"])
        except ValueError as exc:
            messagebox.showerror("Write refused", str(exc))
            return
        if not changes:
            self.status.set("No changes to write")
            return
        if not self.backup or not Path(self.backup).is_file():
            self.save()
            if not self.backup:
                return
        if not messagebox.askyesno(
                "CONFIRM physical write",
                f"Write {len(changes)} modified memory pages to UID {self.snapshot['uid']}?\n\n"
                "This WILL replace its NDEF data. UID, CC, lock/config pages stay untouched.\n"
                "A failed or interrupted write may leave the tag partially programmed.\n\n"
                "Use only a tag you own and can afford to erase."):
            return
        self.status.set("Writing and verifying… Keep the tag still.")
        snap = self.snapshot
        backup = self.backup
        self.execute(
            lambda: perform("write", expected_uid=snap["uid"],
                            expected_data=snap["data"], new_data=image,
                            backup_file=backup),
            self.written)

    def written(self, result):
        self.snapshot = result
        self.backup = None
        self.status.set(f"WRITE VERIFIED · {result['written']} page writes · UID {result['uid']}")
        self.preview()


def main():
    app = tk.Tk()
    Workshop(app)
    app.mainloop()


if __name__ == "__main__":
    main()
