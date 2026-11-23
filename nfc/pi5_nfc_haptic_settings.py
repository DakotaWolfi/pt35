"""Small Tk settings window for PT35 NFC lifecycle vibration cues.

Uses the same DRV2605L lra_ctl helper as the scanner, never accesses I2C here.
"""
import tkinter as tk
from tkinter import ttk, messagebox

from pi5_nfc_haptics import (
    DEFAULT_EVENTS, CONFIG_PATH, load_settings, save_settings, test_effect,
)

TITLES = {
    "scan_start": "Start button pressed",
    "read_start": "Tag reading begins",
    "tag": "Tag successfully read",
    "scan_stop": "Stop / interrupt button",
    "error": "Scanner error",
}


def open_settings(parent):
    """Open a modal settings panel from the recovered NFC GUI Settings page."""
    window = tk.Toplevel(parent)
    window.title("NFC vibration settings")
    window.geometry("550x395")
    window.minsize(460, 350)
    window.transient(parent)
    window.grab_set()

    frame = ttk.Frame(window, padding=12)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Configure each NFC vibration separately").grid(
        row=0, column=0, columnspan=4, sticky="w", pady=(0, 10)
    )
    ttk.Label(frame, text="Event").grid(row=1, column=0, sticky="w")
    ttk.Label(frame, text="Enabled").grid(row=1, column=1)
    ttk.Label(frame, text="Effect ID (1–123)").grid(row=1, column=2)

    old = load_settings()
    flags = {}
    effects = {}
    for row, (event, defaults) in enumerate(DEFAULT_EVENTS.items(), start=2):
        ttk.Label(frame, text=TITLES[event]).grid(
            row=row, column=0, sticky="w", pady=8, padx=(0, 12)
        )
        enabled = tk.BooleanVar(master=window, value=old[event]["enabled"])
        effect = tk.StringVar(master=window, value=str(old[event]["effect"]))
        flags[event], effects[event] = enabled, effect
        ttk.Checkbutton(frame, variable=enabled).grid(row=row, column=1)
        spin = ttk.Spinbox(frame, from_=1, to=123, width=8, textvariable=effect)
        spin.grid(row=row, column=2, padx=8)
        def test_this(e=effect):
            try:
                if not test_effect(e.get()):
                    messagebox.showerror("Haptic test", "lra_ctl is unavailable. Check the NFC error log.", parent=window)
            except ValueError:
                messagebox.showerror("Invalid effect", "Choose an effect number from 1 to 123.", parent=window)
        ttk.Button(frame, text="Test", command=test_this).grid(row=row, column=3)

    ttk.Label(frame, text="Known effects: 1 = Strong click, 10 = Sharp click, 47 = Soft pulse").grid(
        row=7, column=0, columnspan=4, sticky="w", pady=(12, 2)
    )
    ttk.Label(frame, text=f"Saved in {CONFIG_PATH}", wraplength=485).grid(
        row=8, column=0, columnspan=4, sticky="w", pady=(0, 10)
    )

    def save():
        try:
            config = {
                event: {"enabled": flags[event].get(), "effect": int(effects[event].get())}
                for event in DEFAULT_EVENTS
            }
            save_settings(config)
        except (ValueError, OSError, KeyError) as exc:
            messagebox.showerror("Cannot save vibration settings", str(exc), parent=window)
            return
        window.destroy()

    buttons = ttk.Frame(frame)
    buttons.grid(row=9, column=0, columnspan=4, sticky="e", pady=6)
    ttk.Button(buttons, text="Cancel", command=window.destroy).pack(side="right", padx=(8, 0))
    ttk.Button(buttons, text="Save", command=save).pack(side="right")
    frame.columnconfigure(0, weight=1)
    window.bind("<Escape>", lambda event: window.destroy())
    window.protocol("WM_DELETE_WINDOW", window.destroy)
    return window
