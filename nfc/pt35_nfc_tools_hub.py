#!/usr/bin/env python3
"""Persistent PT35 NFC tools menu. Stays alive across child tool launches."""
import argparse
import os
import subprocess
import threading
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOME = Path.home()
VENV = HOME / "as7341-env/bin/python3"


def tool_commands():
    py = str(VENV if VENV.is_file() else Path("/usr/bin/python3"))
    return {
        "Scanner": [str(HOME / ".local/bin/pt35-nfc-gui")],
        "Tag Workshop": [py, str(ROOT / "tag_workshop_gui.py")],
        "Copy tag": [py, str(ROOT / "tag_workshop_batch_gui.py")],
        "Infinite copy": [py, str(ROOT / "tag_workshop_batch_gui.py")],
        "Erase NDEF": [py, str(ROOT / "tag_workshop_gui.py"), "--empty"],
    }


class ToolsHub:
    def __init__(self, root):
        self.root = root
        self.child = None
        self.messages = tk.StringVar(value="Choose an NFC tool. Close it to return here.")
        root.title("PT35 · NFC Tools")
        root.geometry("800x480")
        root.minsize(600, 380)
        root.configure(bg="#151d27")
        tk.Label(root, text="PT35 NFC Tools", font=("DejaVu Sans", 21, "bold"),
                 fg="white", bg="#151d27").pack(anchor="w", padx=16, pady=(12, 6))
        tk.Label(root, textvariable=self.messages, fg="#84d9d1",
                 bg="#151d27", wraplength=750, anchor="w").pack(fill="x", padx=16)
        area = tk.Frame(root, bg="#151d27")
        area.pack(fill="both", expand=True, padx=14, pady=11)
        descriptions = {
            "Scanner": "Auto NFC-A / B / F / V discovery and tag archive",
            "Tag Workshop": "Inspect, edit, save, copy and verify",
            "Copy tag": "Copy source data to a destination tag",
            "Infinite copy": "Automated roll writing — empty-only or overwrite",
            "Erase NDEF": "Format NDEF data as empty; no lock/UID changes",
        }
        for i, (name, command) in enumerate(tool_commands().items()):
            b = tk.Button(area, text=name + "\n" + descriptions[name],
                          command=lambda n=name, c=command: self.launch(n, c),
                          font=("DejaVu Sans", 12), justify="left",
                          bg=("#136d79" if i == 0 else "#263849"),
                          fg="white", relief="flat")
            b.grid(row=i // 2, column=i % 2, padx=5, pady=5, sticky="nsew")
        for i in range(2):
            area.columnconfigure(i, weight=1)
        for i in range(3):
            area.rowconfigure(i, weight=1)
        tk.Button(root, text="Exit NFC Tools", command=self.close,
                  bg="#33465a", fg="white", height=1,
                  font=("DejaVu Sans", 12)).pack(fill="x", padx=17, pady=(0, 9))
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Escape>", lambda _: self.close())

    def launch(self, name, command):
        if self.child and self.child.poll() is None:
            return
        if not Path(command[0]).exists():
            self.messages.set("Tool not installed: " + command[0])
            return
        try:
            self.child = subprocess.Popen(command, cwd=str(ROOT))
        except OSError as exc:
            self.messages.set(f"Unable to start {name}: {exc}")
            return
        self.messages.set(name + " launched. Close tool to return.")
        self.root.withdraw()
        proc = self.child
        def watch():
            returncode = proc.wait()
            self.root.after(0, lambda: self.comeback(name, returncode))
        threading.Thread(target=watch, daemon=True).start()

    def comeback(self, name, code):
        if not self.root.winfo_exists():
            return
        self.child = None
        self.messages.set(
            f"{name} closed (status {code}). Select another tool."
            if code else f"{name} closed. Choose another tool.")
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def close(self):
        if self.child is not None and self.child.poll() is None:
            self.messages.set("Close the active NFC tool before exiting the hub.")
            return
        self.root.destroy()


if __name__ == "__main__":
    app = tk.Tk()
    ToolsHub(app)
    app.mainloop()
