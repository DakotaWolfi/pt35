#!/usr/bin/env python3
"""PT35 continuous Type 2 writer. Reuses verified Workshop RF writer.

One source image, many distinct destination tags. Each physical presentation
is verified; source removal is mandatory before the batch can begin.
"""
import argparse
import queue
import shutil
import socket
import os
import subprocess
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from tag_workshop_batch import destination_decision, image_for
from tag_workshop_ndef import parse
from tag_workshop_rf import perform, save_backup


def led(*words):
    """Use the same user LED daemon socket for every NFC copy effect."""
    path = os.environ.get("PT35_LED_SOCKET", f"/run/user/{os.getuid()}/pt35-led.sock")
    try:
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(.25)
            sock.connect(path)
            sock.sendall((" ".join(map(str, words)) + "\n").encode("ascii"))
            return sock.recv(128).decode("ascii", "replace").strip()
    except (OSError, TimeoutError):
        return None


def led_progress(done, total):
    led("nfc-progress", done, total)


def presence():
    """Quick read-only UID probe; no memory operation or tag writes."""
    from smbus2 import SMBus
    from tag_workshop_rf import driver
    configure, poll_a, _, _, Reader, reader_lock, FrameError = driver()
    with reader_lock("i2c-1"), SMBus(1) as bus:
        chip = Reader(bus)
        try:
            chip.initialize(configure=lambda dev: configure(dev, "NFC-A"))
            try:
                uid, _ = poll_a(chip)
                return uid
            except (FrameError, TimeoutError, OSError):
                return None
        finally:
            try:
                chip.shutdown()
            except OSError:
                pass


class BatchApp:
    def __init__(self, root, *, once=False):
        self.root = root
        self.once = once
        root.title("PT35 · NFC Copy")
        root.geometry("800x480")
        root.minsize(620, 400)
        root.configure(bg="#151e29")
        self.events = queue.Queue()
        self.stop_event = threading.Event()
        self.thread = None
        self.source = None
        self.seen = set()
        self.attempted = set()
        self.count = 0
        self.skips = 0
        self.fails = 0
        self.mode = tk.StringVar(value="NDEF")
        self.policy = tk.StringVar(value="empty")
        self.quantity = tk.StringVar(value="continuous")
        self.allow_rewrite = tk.BooleanVar(value=False)
        self.state = tk.StringVar(value="1. Scan a source sticker to capture its data.")
        self.source_label = tk.StringVar(value="Source: not selected")
        self.counter = tk.StringVar(value="Written: 0    Skipped: 0    Failed: 0")
        tk.Label(root, text="NFC Copy", bg="#151e29", fg="white",
                 font=("DejaVu Sans", 21, "bold")).pack(anchor="w", padx=15, pady=(9, 3))
        tk.Label(root, textvariable=self.state, bg="#151e29", fg="#6ce0d0",
                 font=("DejaVu Sans", 12), wraplength=750, justify="left",
                 anchor="w").pack(fill="x", padx=15, pady=3)
        tk.Label(root, textvariable=self.source_label, bg="#151e29", fg="white",
                 font=("DejaVu Sans", 11), wraplength=750,
                 anchor="w").pack(fill="x", padx=15, pady=3)
        opts = tk.Frame(root, bg="#151e29")
        opts.pack(fill="x", padx=12, pady=9)
        tk.Label(opts, text="Copy:", bg="#151e29", fg="white").pack(side="left")
        for label, value in (("NDEF content", "NDEF"), ("RAW user bytes", "RAW")):
            tk.Radiobutton(opts, text=label, value=value, variable=self.mode,
                           bg="#151e29", fg="white", selectcolor="#263847",
                           activebackground="#151e29", activeforeground="white"
                           ).pack(side="left", padx=5)
        opts2 = tk.Frame(root, bg="#151e29")
        opts2.pack(fill="x", padx=12)
        tk.Label(opts2, text="Destination:", bg="#151e29", fg="white").pack(side="left")
        for label, value in (("Only empty tags", "empty"), ("Overwrite existing data", "overwrite")):
            tk.Radiobutton(opts2, text=label, value=value, variable=self.policy,
                           bg="#151e29", fg="white", selectcolor="#263847",
                           activebackground="#151e29", activeforeground="white"
                           ).pack(side="left", padx=4)
        tk.Checkbutton(
            root, text="Allow rewriting a tag handled earlier in this batch (after removal)",
            variable=self.allow_rewrite, bg="#151e29", fg="white",
            selectcolor="#263847", activebackground="#151e29",
            activeforeground="white", anchor="w"
        ).pack(fill="x", padx=16, pady=(4, 0))
        run_row = tk.Frame(root, bg="#151e29")
        run_row.pack(fill="x", padx=12, pady=(2, 0))
        tk.Label(run_row, text="Run:", bg="#151e29", fg="white").pack(side="left")
        for label, value in (("One tag", "one"), ("Continuous", "continuous")):
            tk.Radiobutton(run_row, text=label, value=value, variable=self.quantity,
                           bg="#151e29", fg="white", selectcolor="#263847",
                           activebackground="#151e29", activeforeground="white"
                           ).pack(side="left", padx=8)
        self.details = tk.Text(root, bg="#263847", fg="#eef7ff", wrap="word",
                               height=5, font=("DejaVu Sans", 11))
        self.details.pack(fill="both", expand=True, padx=15, pady=6)
        self.details.insert("1.0", "Source preview and last results will appear here.")
        self.details.config(state="disabled")
        tk.Label(root, textvariable=self.counter, bg="#151e29", fg="white",
                 font=("DejaVu Sans", 12, "bold")).pack(fill="x", padx=15)
        bottom = tk.Frame(root, bg="#151e29")
        bottom.pack(fill="x", padx=12, pady=(5, 12))
        self.read_button = tk.Button(bottom, text="1 · Scan source", command=self.scan_source,
                                     bg="#147b85", fg="white", height=2)
        self.read_button.pack(side="left", fill="x", expand=True, padx=3)
        self.start_button = tk.Button(bottom, text="2 · Start batch", command=self.start,
                                     bg="#30623f", fg="white", height=2)
        self.start_button.pack(side="left", fill="x", expand=True, padx=3)
        self.stop_button = tk.Button(bottom, text="Stop", command=self.stop,
                                    bg="#9b4444", fg="white", height=2)
        self.stop_button.pack(side="left", fill="x", expand=True, padx=3)
        tk.Button(bottom, text="Exit", command=self.close,
                  bg="#344152", fg="white", height=2).pack(side="left", fill="x", expand=True, padx=3)
        self.root.after(80, self.pump)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Escape>", lambda _: self.stop())

    def show_text(self, text):
        self.details.config(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.config(state="disabled")

    def update_counters(self):
        self.counter.set(f"Written: {self.count}    Skipped: {self.skips}    Failed: {self.fails}")

    def pump(self):
        try:
            while True:
                event, value = self.events.get_nowait()
                if event == "state":
                    self.state.set(value)
                elif event == "source":
                    self.source = value
                    self.source_label.set(
                        f"Source UID: {value['uid']} · {value['capacity']} bytes")
                    try:
                        kind, text = parse(value["data"])
                        rendered = f"NDEF {kind}: {text[:400]}"
                    except (ValueError, UnicodeError):
                        rendered = "Non-standard / raw data — use RAW copy"
                    self.show_text(rendered + "\n\nVerify this source, choose the options, then Start batch.")
                    self.read_button.config(state="normal")
                    self.start_button.config(state="normal")
                elif event == "result":
                    status, uid, detail = value
                    if status == "write":
                        self.count += 1
                    elif status == "skip":
                        self.skips += 1
                    elif status == "error":
                        self.fails += 1
                    self.update_counters()
                    self.show_text(f"{status.upper()}: {uid}\n{detail}\n\n"
                                   f"Written {self.count} | skipped {self.skips} | failed {self.fails}")
                elif event == "idle":
                    self.read_button.config(state="normal")
                    self.start_button.config(state="normal")
                    self.mode_menu("normal")
                elif event == "error":
                    self.state.set("Error: " + str(value))
                    self.read_button.config(state="normal")
                    self.start_button.config(state="normal")
                    messagebox.showerror("NFC Infinite Copy", str(value))
        except queue.Empty:
            pass
        self.root.after(80, self.pump)

    def mode_menu(self, state):
        pass

    def scan_source(self):
        if self.thread and self.thread.is_alive():
            messagebox.showinfo("Busy", "Stop the current operation first.")
            return
        self.stop_event.clear()
        self.read_button.config(state="disabled")
        self.start_button.config(state="disabled")
        self.state.set("Reading source — keep ONE tag near the antenna.")
        def task():
            try:
                result = perform("read")
                if not self.stop_event.is_set():
                    self.events.put(("source", result))
                    self.events.put(("state", "Source captured. Review and confirm before copying."))
            except Exception as exc:
                self.events.put(("error", str(exc)))
            finally:
                self.events.put(("idle", None))
        self.thread = threading.Thread(target=task, daemon=True)
        self.thread.start()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        if not self.source:
            messagebox.showinfo("Select source", "Scan a source sticker first.")
            return
        copy_mode = self.mode.get().lower()
        policy = self.policy.get()
        allow_rewrite = self.allow_rewrite.get()
        once = self.quantity.get() == "one"
        try:
            image_for(self.source, self.source, copy_mode)
        except (ValueError, KeyError) as exc:
            messagebox.showerror("Invalid source", str(exc))
            return
        if not messagebox.askyesno(
            "Start automatic tag copying",
            f"Source: {self.source['uid']}\n"
            f"Mode: {copy_mode.upper()}\n"
            f"Destination policy: {'Empty tags only' if policy == 'empty' else 'OVERWRITE existing data'}\n"
            f"Reuse previously written UID: {'YES (after removal)' if allow_rewrite else 'NO'}\n\n"
            "Every different compatible tag presented will be backed up, written, "
            "and verified automatically. Keep the source away.\n"
            "Stop can take effect after the current tag operation. Proceed?"):
            return
        self.stop_event.clear()
        self.read_button.config(state="disabled")
        self.start_button.config(state="disabled")
        source = {**self.source, "data": bytes(self.source["data"])}
        self.thread = threading.Thread(target=self.loop, args=(source, copy_mode, policy, allow_rewrite, once),
                                       daemon=True)
        self.thread.start()

    def loop(self, source, mode, policy, allow_rewrite, once):
        led("nfc")
        # Source was just scanned. Require physical removal to arm batch.
        self.events.put(("state", "REMOVE source tag. Waiting for clear antenna..."))
        removed_count = 0
        try:
            while not self.stop_event.is_set():
                uid = presence()
                if uid is None:
                    removed_count += 1
                else:
                    removed_count = 0
                if removed_count >= 3:
                    break
                self.stop_event.wait(0.35)
            if self.stop_event.is_set():
                return
            self.events.put(("state", "READY · Present a destination tag. Remove after each result."))
            blocked_uid = None
            clear_count = 3
            while not self.stop_event.is_set():
                try:
                    uid = presence()
                except (OSError, RuntimeError) as exc:
                    self.events.put(("state", "Reader warning: " + str(exc)[:110]))
                    self.stop_event.wait(.5)
                    continue
                if not uid:
                    clear_count = min(3, clear_count + 1)
                    if clear_count >= 3:
                        blocked_uid = None
                    self.stop_event.wait(.3)
                    continue
                if blocked_uid is not None or clear_count < 3:
                    self.stop_event.wait(.3)
                    continue
                blocked_uid = uid
                clear_count = 0
                if uid == source["uid"]:
                    self.events.put(("result", ("skip", uid, "Source tag ignored.")))
                    continue
                self.events.put(("state", "Reading " + uid + " for compatibility / protection..."))
                try:
                    destination = perform("read")
                    # A previously handled UID is reusable only after complete
                    # antenna removal AND explicit user opt-in; failed writes
                    # require manual inspection before another automatic attempt.
                    guarded = self.attempted | (set() if allow_rewrite else self.seen)
                    decision, detail = destination_decision(
                        source, destination, mode, policy, guarded)
                    if decision == "skip":
                        self.events.put(("result", ("skip", uid, detail)))
                        continue
                    if decision == "same":
                        self.events.put(("result", ("skip", uid, "Already matches source.")))
                        continue
                    image = detail
                    self.attempted.add(destination["uid"])  # never auto-repeat after ambiguous failure
                    original_backup = save_backup(destination)
                    # The RF writer will scan and match UID + all original
                    # bytes a second time, and verify the completed write.
                    led("nfc-progress", "1", "2")
                    result = perform(
                        "write", expected_uid=destination["uid"],
                        expected_data=destination["data"],
                        new_data=image, backup_file=original_backup,
                        raw_transfer=True, progress=led_progress)
                    self.seen.add(result["uid"])
                    self.attempted.discard(result["uid"])
                    led("nfc-success")
                    self.events.put(("result", (
                        "write", result["uid"],
                        f"Verified {result['written']} page writes; backup: {original_backup.name}")))
                    if once:
                        # Let the user see the verified-green cue before
                        # ending the batch and restoring the normal LED mode.
                        time.sleep(1.0)
                        self.stop_event.set()
                except Exception as exc:
                    led("nfc-fail")
                    self.events.put(("result", ("error", uid, str(exc))))
                    self.events.put(("state", "ERROR · Remove tag and inspect it before another attempt."))
                finally:
                    # The daemon restores blue after the longer result cue.
                    self.events.put(("state", "Remove tag, then present the next one."))
                self.stop_event.wait(.35)
        except Exception as exc:
            self.events.put(("error", str(exc)))
        finally:
            led("idle")
            self.events.put(("idle", None))
            self.events.put(("state", "Batch stopped. Source remains available for another run."))

    def stop(self):
        self.stop_event.set()
        self.state.set("Stopping after the current NFC operation...")

    def close(self):
        self.stop_event.set()
        self.root.destroy()


def main():
    root = tk.Tk()
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Stop after first verified write")
    args = parser.parse_args()
    window = BatchApp(root, once=args.once)
    if args.once:
        window.quantity.set("one")
    root.mainloop()


if __name__ == "__main__":
    main()
