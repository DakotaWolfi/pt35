"""Small Tk widgets for PT35's touch screens."""
import tkinter as tk

BG = '#101923'
PANEL = '#1d2c3a'
FG = '#f2f7fb'
MUTED = '#becfdf'
ACCENT = '#76e8bb'
INK = '#0c241c'
BORDER = '#456076'
FONT = ('DejaVu Sans', -17)
SMALL = ('DejaVu Sans', -15)
LARGE = ('DejaVu Sans', -23, 'bold')
MONO = ('DejaVu Sans Mono', -16)


class Button(tk.Button):
    def __init__(self, parent, text, command, *, primary=False, selected=False, lines=1, **kwargs):
        light = primary or selected
        super().__init__(parent, text=text, command=command, bg=ACCENT if light else PANEL,
                         fg=INK if light else FG, activebackground='#a3f3d4' if light else BORDER,
                         activeforeground=INK if light else FG, disabledforeground='#8295a8',
                         font=FONT, justify='left', relief='flat', borderwidth=0, highlightthickness=0,
                         padx=8, pady=15, height=lines, takefocus=True, **kwargs)


def label(parent, text='', *, font=FONT, fg=FG, bg=BG, **kwargs):
    return tk.Label(parent, text=text, bg=bg, fg=fg, font=font, anchor='w', justify='left', **kwargs)


def row(parent, buttons, gap=6):
    bar = tk.Frame(parent, bg=BG)
    for index, (title, action, options) in enumerate(buttons):
        bar.grid_columnconfigure(index, weight=1, uniform='touch')
        Button(bar, title, action, **options).grid(row=0, column=index, sticky='nsew',
                                                    padx=(0, gap if index + 1 < len(buttons) else 0))
    return bar


class ScrollArea(tk.Frame):
    """Vertical swipe with drag suppression for buttons and a wide scrollbar."""
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, yscrollincrement=1)
        self.scrollbar = tk.Scrollbar(self, orient='vertical', command=self.canvas.yview,
                                     width=44, bg=BORDER, troughcolor=PANEL,
                                     activebackground=ACCENT, borderwidth=0, highlightthickness=0)
        self.canvas.configure(yscrollcommand=self.set_scrollbar)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.content = tk.Frame(self.canvas, bg=BG)
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
