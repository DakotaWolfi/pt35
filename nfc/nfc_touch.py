"""Small Tk widgets for PT35's touch screens."""
import tkinter as tk
from tkinter import font as tkfont
from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    background: str
    panel: str
    text: str
    muted: str
    accent: str
    accent_text: str
    border: str
    pressed: str
    accent_pressed: str
    disabled: str


THEMES = {
    'dark': Palette(background='#101923', panel='#1d2c3a', text='#f2f7fb', muted='#becfdf',
                    accent='#76e8bb', accent_text='#0c241c', border='#456076',
                    pressed='#456076', accent_pressed='#a3f3d4', disabled='#8295a8'),
    'light': Palette(background='#f5f8fb', panel='#e4ecf3', text='#152738', muted='#41586d',
                     accent='#9ae8c7', accent_text='#0c241c', border='#61798b',
                     pressed='#cbdbe9', accent_pressed='#b3f1d8', disabled='#506879'),
}
FONT = ('DejaVu Sans', -17)
SMALL = ('DejaVu Sans', -15)
LARGE = ('DejaVu Sans', -23, 'bold')
MONO = ('DejaVu Sans Mono', -16)


def palette_for(parent):
    return getattr(parent.winfo_toplevel(), 'palette', THEMES['dark'])


def font_for(parent, spec):
    top = parent.winfo_toplevel()
    if not hasattr(top, 'ui_fonts'):
        return spec
    if spec not in top.ui_fonts:
        top.ui_fonts[spec] = tkfont.Font(root=top, family=spec[0], size=round(spec[1] * top.ui_scale),
                                       weight=spec[2] if len(spec) > 2 else 'normal')
    return top.ui_fonts[spec]


def touch_size(parent, pixels):
    return round(pixels * getattr(parent.winfo_toplevel(), 'ui_scale', 1))


class Button(tk.Button):
    def __init__(self, parent, text, command, *, primary=False, selected=False, lines=1, **kwargs):
        palette = palette_for(parent)
        accent = primary or selected
        text_color = palette.accent_text if accent else palette.text
        super().__init__(parent, text=text, command=command, bg=palette.accent if accent else palette.panel,
                         fg=text_color, activebackground=palette.accent_pressed if accent else palette.pressed,
                         activeforeground=text_color, disabledforeground=palette.disabled,
                         font=font_for(parent, FONT), justify='left', relief='flat', borderwidth=0, highlightthickness=0,
                         padx=8, pady=touch_size(parent, 15), height=lines, takefocus=True, **kwargs)


def label(parent, text='', *, font=FONT, muted=False, **kwargs):
    palette = palette_for(parent)
    return tk.Label(parent, text=text, bg=palette.background, fg=palette.muted if muted else palette.text,
                    font=font_for(parent, font), anchor='w', justify='left', **kwargs)


def row(parent, buttons, gap=6):
    bar = tk.Frame(parent, bg=palette_for(parent).background)
    for index, (title, action, options) in enumerate(buttons):
        bar.grid_columnconfigure(index, weight=1, uniform='touch')
        Button(bar, title, action, **options).grid(row=0, column=index, sticky='nsew',
                                                    padx=(0, gap if index + 1 < len(buttons) else 0))
    return bar


class ScrollArea(tk.Frame):
    """Vertical swipe with drag suppression for buttons and a wide scrollbar."""
    def __init__(self, parent):
        palette = palette_for(parent)
        super().__init__(parent, bg=palette.background)
        self.canvas = tk.Canvas(self, bg=palette.background, highlightthickness=0, yscrollincrement=1)
        self.scrollbar = tk.Scrollbar(self, orient='vertical', command=self.canvas.yview,
                                     width=touch_size(parent, 44), bg=palette.border, troughcolor=palette.panel,
                                     activebackground=palette.accent, borderwidth=0, highlightthickness=0)
        self.canvas.configure(yscrollcommand=self.set_scrollbar)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.content = tk.Frame(self.canvas, bg=palette.background)
        self.window = self.canvas.create_window(0, 0, window=self.content, anchor='nw')
        self.content.bind('<Configure>', self.update_scrollregion)
        self.canvas.bind('<Configure>', lambda event: self.canvas.itemconfigure(self.window, width=event.width))
        self.origin = None
        self.dragging = False
        self.enable_swipe(self.canvas)

    def set_scrollbar(self, start, end):
        self.scrollbar.set(start, end)
        needs_scroll = float(start) > 0 or float(end) < 1
        if needs_scroll and not self.scrollbar.winfo_manager():
            self.scrollbar.pack(side='right', fill='y', padx=(6, 0), before=self.canvas)
        elif not needs_scroll and self.scrollbar.winfo_manager():
            self.scrollbar.pack_forget()

    def update_scrollregion(self, event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))

    def enable_swipe(self, widget=None):
        widget = self.content if widget is None else widget
        widget.bind('<ButtonPress-1>', self.press, add='+')
        widget.bind('<B1-Motion>', self.move, add='+')
        widget.bind('<ButtonRelease-1>', self.release, add='+')
        widget.bind('<Button-4>', lambda _: self.canvas.yview_scroll(-50, 'units'), add='+')
        widget.bind('<Button-5>', lambda _: self.canvas.yview_scroll(50, 'units'), add='+')
        widget.bind('<MouseWheel>', lambda e: self.canvas.yview_scroll(-int(e.delta / 120) * 50, 'units'), add='+')
        for child in widget.winfo_children():
            self.enable_swipe(child)

    def press(self, event):
        self.origin = self.last_y = event.y_root
        self.dragging = False

    def move(self, event):
        if self.origin is not None and (self.dragging or abs(event.y_root - self.origin) > 9):
            self.dragging = True
            self.canvas.yview_scroll(self.last_y - event.y_root, 'units')
            self.last_y = event.y_root
            return 'break'

    def release(self, event):
        self.origin = None
        if self.dragging:
            self.dragging = False
            # Let Tk's Button release finish resetting its press state with
            # the pointer outside the button, so a swipe cannot invoke it.
            if isinstance(event.widget, tk.Button):
                event.widget.event_generate('<Leave>')
            return 'break'
        return None
