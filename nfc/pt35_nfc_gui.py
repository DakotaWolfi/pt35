#!/usr/bin/env python3
"""PT35 NFC graphical front end (Tkinter).

Runs the existing pt35_nfc.py backend; never manipulates RF hardware itself.
Archives stay in the existing ~/pt35-nfc/archive directory.
"""
from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

HERE = Path(__file__).resolve().parent
BACKEND_SCRIPT = HERE / "pt35_nfc.py"
ARCHIVE = Path.home() / "pt35-nfc" / "archive"
POLL_MS = 100


class NFCWindow(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PT35 NFC Reader")
        self.geometry("850x620")
        self.minsize(620, 440)
        self.events = queue.Queue()
        self.proc = None
        self.busy = False
        self.backend = tk.StringVar(value="auto")
        self.auto_tonie = tk.BooleanVar(value=True)
        self.save_all = tk.BooleanVar(value=False)
        self.include_st = tk.BooleanVar(value=False)
        self.blocks = tk.StringVar(value="0")
        self.state = tk.StringVar(value="Ready")
        self._build()
        self.refresh_archive()
        self.after(POLL_MS, self._drain_events)
        self.protocol("WM_DELETE_WINDOW", self.close)
        if not BACKEND_SCRIPT.is_file():
            messagebox.showerror("Missing backend", f"Cannot find {BACKEND_SCRIPT}")

    def _build(self):
        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)
        opts = ttk.LabelFrame(outer, text="Reader", padding=8)
        opts.pack(fill="x")
        ttk.Label(opts, text="Backend").grid(row=0, column=0, sticky="w")
        ttk.Combobox(opts, textvariable=self.backend, state="readonly", width=13,
                     values=("auto", "internal", "proxmark3")).grid(row=0, column=1, padx=6)
        ttk.Label(opts, text="Blocks (0 = auto)").grid(row=0, column=2, sticky="w", padx=(10, 0))
        ttk.Spinbox(opts, from_=0, to=256, textvariable=self.blocks, width=6).grid(row=0, column=3, padx=6)
        ttk.Checkbutton(opts, text="Auto-save Tonie candidates", variable=self.auto_tonie).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(9, 0))
        ttk.Checkbutton(opts, text="Save every tag", variable=self.save_all).grid(
            row=1, column=2, columnspan=2, sticky="w", pady=(9, 0))
        ttk.Checkbutton(opts, text="Include built-in ST tag", variable=self.include_st).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(5, 0))
        bar = ttk.Frame(outer)
        bar.pack(fill="x", pady=8)
        self.start_button = ttk.Button(bar, text="Start scanning", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(bar, text="Stop", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=5)
        ttk.Button(bar, text="Reader status", command=lambda: self.run_once("status")).pack(side="left", padx=5)
        ttk.Button(bar, text="Identify (PM3)", command=lambda: self.run_once("identify")).pack(side="left", padx=5)
        ttk.Label(bar, textvariable=self.state).pack(side="right")
        logbox = ttk.LabelFrame(outer, text="Live scanner output", padding=5)
        logbox.pack(fill="both", expand=True)
        self.log = tk.Text(logbox, height=10, wrap="word", state="disabled")
        log_scroll = ttk.Scrollbar(logbox, command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set)
        self.log.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")
        archivebox = ttk.LabelFrame(outer, text="Saved tags", padding=5)
        archivebox.pack(fill="both", expand=True, pady=(8, 0))
        cols = ("uid", "type", "status", "reader")
        self.tree = ttk.Treeview(archivebox, columns=cols, show="headings", height=7)
        for col, width in (("uid", 185), ("type", 170), ("status", 175), ("reader", 90)):
            self.tree.heading(col, text=col.capitalize())
            self.tree.column(col, width=width, minwidth=70)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", lambda _: self.show_selected())
        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", pady=(7, 0))
        ttk.Button(bottom, text="Refresh archive", command=self.refresh_archive).pack(side="left")
        ttk.Button(bottom, text="View selected tag", command=self.show_selected).pack(side="left", padx=6)
        ttk.Label(bottom, text=f"Archive: {ARCHIVE}").pack(side="right")

    def _append(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg.rstrip("\n") + "\n")
        # Keep memory use bounded on long scans.
        if int(self.log.index("end-1c").split(".")[0]) > 1800:
            self.log.delete("1.0", "301.0")
        self.log.see("end")
        self.log.configure(state="disabled")
        if "Archived:" in msg:
            self.refresh_archive()

    def _command(self, action):
        try:
            count = int(self.blocks.get())
        except ValueError as exc:
            raise ValueError("Block count must be an integer from 0 to 256") from exc
        if not 0 <= count <= 256:
            raise ValueError("Block count must be between 0 and 256")
        cmd = [sys.executable, "-u", str(BACKEND_SCRIPT), action,
               "--backend", self.backend.get(), "--archive", str(ARCHIVE),
               "--blocks", str(count)]
        if self.auto_tonie.get(): cmd.append("--auto-tonie")
        if self.save_all.get(): cmd.append("--save")
        if self.include_st.get(): cmd.append("--include-st")
        return cmd

    def start(self):
        self._launch("watch")

    def run_once(self, action):
        self._launch(action)

    def _launch(self, action):
        if self.proc is not None:
            return
        try:
            cmd = self._command(action)
        except ValueError as exc:
            messagebox.showerror("Invalid setting", str(exc))
            return
        self._append(f"$ {' '.join(cmd)}")
        try:
            self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                         text=True, bufsize=1, start_new_session=True)
        except OSError as exc:
            self._append(f"Cannot launch scanner: {exc}")
            self.proc = None
            return
        self.busy = True
        self.state.set("Scanning" if action == "watch" else f"Running {action}")
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        proc = self.proc
        threading.Thread(target=self._read_output, args=(proc,), daemon=True).start()

    def _read_output(self, proc):
        try:
            for line in proc.stdout:
                self.events.put(("line", line))
            rc = proc.wait()
            self.events.put(("exit", proc, rc))
        except Exception as exc:
            self.events.put(("line", f"Scanner output error: {exc}"))
            self.events.put(("exit", proc, -1))

    def _drain_events(self):
        try:
            while True:
                entry = self.events.get_nowait()
                if entry[0] == "line":
                    self._append(entry[1])
                elif entry[0] == "exit":
                    _, proc, rc = entry
                    if self.proc is proc:
                        self.proc = None
                        self.busy = False
                        self.state.set(f"Stopped (exit {rc})")
                        self.start_button.configure(state="normal")
                        self.stop_button.configure(state="disabled")
                        self.refresh_archive()
        except queue.Empty:
            pass
        self.after(POLL_MS, self._drain_events)

    def stop(self):
        proc = self.proc
        if proc is None or proc.poll() is not None:
            return
        self.state.set("Stopping...")
        # Kill the process group after grace period; worker thread never touches Tk.
        try:
            os.killpg(proc.pid, signal.SIGINT)
        except ProcessLookupError:
            pass
        self.after(2500, lambda: self._force_stop(proc))

    def _force_stop(self, proc):
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def refresh_archive(self):
        selected = self.tree.selection()
        selected_uid = self.tree.item(selected[0], "values")[0] if selected else None
        self.tree.delete(*self.tree.get_children())
        for path in sorted(ARCHIVE.glob("*/record.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                uid = record.get("uid", path.parent.name)
                kind = record.get("tonie_status", record.get("classification", "unknown"))
                self.tree.insert("", "end", values=(
                    uid, kind, record.get("dump_status", "unknown"), record.get("backend", "?")))
            except (OSError, ValueError, TypeError):
                continue
        if selected_uid:
            for item in self.tree.get_children():
                if self.tree.item(item, "values")[0] == selected_uid:
                    self.tree.selection_set(item)
                    break

    def show_selected(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("Saved tags", "Select a tag first.")
            return
        uid = self.tree.item(selected[0], "values")[0]
        path = ARCHIVE / uid / "record.json"
        try:
            content = json.dumps(json.loads(path.read_text(encoding="utf-8")), indent=2)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Cannot open record", str(exc))
            return
        window = tk.Toplevel(self)
        window.title(f"Tag {uid}")
        window.geometry("720x520")
        body = tk.Text(window, wrap="none")
        body.insert("1.0", content)
        body.configure(state="disabled")
        body.pack(fill="both", expand=True)

    def close(self):
        if self.proc is not None and self.proc.poll() is None:
            self.stop()
            self.after(400, self._finish_close)
        else:
            self.destroy()

    def _finish_close(self):
        proc = self.proc
        if proc and proc.poll() is None:
            try: os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError: pass
        self.destroy()


if __name__ == "__main__":
    NFCWindow().mainloop()
