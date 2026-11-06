#!/usr/bin/env python3
"""PT35 terminal diagnostics. Writes only AS7341 configuration at I2C 0x39 for the spectral tool."""
import argparse
import curses
import os
import subprocess
import sys
import time

VENV_PY = os.path.expanduser('~/as7341-env/bin/python')
DEVICES = [('AS7341 spectral analyzer', 'as7341'),
           ('ST25DV16K NFC tag (status)', 'nfc'),
           ('ST25R3916 NFC reader (planned)', 'reader'),
           ('NeoPixels (integration pending)', 'neo'),
           ('LEDs (integration pending)', 'led'),
           ('I2C bus scan', 'i2c'),
           ('Exit', 'exit')]
WAVES = [415,445,480,515,555,590,630,680]


def scan_bus():
    try:
        from smbus2 import SMBus
        with SMBus(1) as bus:
            found = []
            for addr in range(0x08, 0x78):
                try:
                    bus.read_byte(addr)
                    found.append(addr)
                except OSError:
                    pass
            return found
    except ImportError:
        return None


def safe_add(win, y, x, msg, attr=0):
    h, w = win.getmaxyx()
    if y < h and x < w:
        try:
            win.addnstr(y, x, str(msg), max(0,w-x-1), attr)
        except curses.error:
            pass


def page(win, title, lines):
    while True:
        win.erase()
        safe_add(win,0,0,title,curses.A_BOLD)
        for i, line in enumerate(lines,2):
            safe_add(win,i,0,line)
        safe_add(win,win.getmaxyx()[0]-1,0,'Press any key to return')
        win.refresh()
        if win.getch() != -1:
            return


def init_spectral_colors():
    """Best-effort 256-color palette, falling back to the terminal's basic colors."""
    if not curses.has_colors():
        return False
    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except curses.error:
        bg = curses.COLOR_BLACK
    # xterm-256 approximate rainbow; 8/16-color terminals use classic colors.
    vivid = [135, 63, 39, 43, 113, 220, 208, 167]
    basic = [curses.COLOR_MAGENTA, curses.COLOR_BLUE, curses.COLOR_CYAN,
             curses.COLOR_GREEN, curses.COLOR_GREEN, curses.COLOR_YELLOW,
             curses.COLOR_YELLOW, curses.COLOR_RED]
    for i, color in enumerate(vivid if curses.COLORS >= 256 else basic, 1):
        try:
            curses.init_pair(i, color, bg)
        except curses.error:
            return False
    return True


def reset_as7341_mode():
    """Recover AS7341 spectral operation after the driver's flicker mode.

    Flicker programming selects coefficient RAM bank 1 via CFG0 (0xA9).
    The previous reset cleared ENABLE but did not restore CFG0, so spectral
    SMUX writes could target the wrong bank. Touches only I2C address 0x39.
    """
    from smbus2 import SMBus
    with SMBus(1) as bus:
        bus.write_byte_data(0x39, 0x80, 0x00)  # disable measurement / flicker
        time.sleep(0.03)
        bus.write_byte_data(0x39, 0xA9, 0x00)  # select normal register/RAM bank
        time.sleep(0.03)


def make_as7341(board, adafruit_as7341, reset=True):
    if reset:
        reset_as7341_mode()
    sensor = adafruit_as7341.AS7341(board.I2C())
    sensor.led_current = 4
    sensor.led = False
    return sensor


def sensor_page(win):
    try:
        import board
        import adafruit_as7341
        sensor = make_as7341(board, adafruit_as7341)
    except Exception as ex:
        page(win, 'AS7341 initialization failed',
             [repr(ex), 'Check address 0x39 and sensor libraries.'])
        return

    colors = init_spectral_colors()
    win.timeout(100)
    vals = None
    clear = None
    nir = None
    last_error = ''
    last = 0.0
    flicker_mode = False
    flicker = None
    led_on = False
    hiccups = 0
    try:
        while True:
            key = win.getch()
            if key in (ord('q'), ord('Q'), ord('y'), ord('Y'), 27):
                break
            if key in (ord('l'), ord('L')):
                try:
                    sensor.led = not led_on
                    led_on = not led_on
                    last_error = ''
                    last = 0
                except OSError as ex:
                    last_error = 'LED control: ' + repr(ex)
            if key in (ord('f'), ord('F')) and not flicker_mode:
                last_error = 'Flicker temporarily disabled: RAM-bank recovery under test'
            if key in (ord('r'), ord('R'), ord('z'), ord('Z')):
                # Always clear the hardware's flicker-enable bit (FDEN),
                # then create a new driver object with clean cached SMUX state.
                try:
                    sensor.led = False
                    sensor = make_as7341(board, adafruit_as7341)
                    led_on = False
                    flicker_mode = False
                    flicker = None
                    vals = clear = nir = None
                    last_error = ''
                    last = 0
                except Exception as ex:
                    last_error = 'Sensor recovery: ' + repr(ex)
                    last = time.monotonic()

            if time.monotonic() - last >= (0.5 if flicker_mode else 0.4):
                for attempt in range(3):
                    try:
                        if flicker_mode:
                            flicker = sensor.flicker_detected
                        else:
                            new_vals = sensor.all_channels
                            new_clear = sensor.channel_clear
                            new_nir = sensor.channel_nir
                            vals, clear, nir = new_vals, new_clear, new_nir
                        last_error = ''
                        break
                    except OSError as ex:
                        last_error = repr(ex)
                        hiccups += 1
                        time.sleep(0.04)
                    except Exception as ex:
                        last_error = repr(ex)
                        break
                last = time.monotonic()

            win.erase()
            safe_add(win, 0, 0, 'AS7341 - PT35 spectral analyzer v2.2 recovery', curses.A_BOLD)
            safe_add(win, 1, 0, f'LED: {"ON" if led_on else "OFF"} (4 mA) | L LED | F unavailable | R/Z reset spectrum')
            if flicker_mode:
                safe_add(win, 3, 0, 'FLICKER DETECTOR', curses.A_BOLD)
                safe_add(win, 5, 0, f'Detected: {str(flicker) + " Hz" if flicker is not None else "none / unsupported"}')
                safe_add(win, 7, 0, 'Driver detects 1000/1200 Hz only, NOT 50/60 Hz.')
                safe_add(win, 8, 0, 'Spectral acquisition paused. R/Z = reset to spectrum.')
            else:
                safe_add(win, 2, 0, 'Relative counts, NOT calibrated irradiance')
                if vals is not None:
                    peak = max(max(vals), 1)
                    width = max(1, min(34, win.getmaxyx()[1] - 19))
                    for i, (nm, value) in enumerate(zip(WAVES, vals)):
                        prefix = f'{nm:3d} nm  {value:5d} |'
                        safe_add(win, 4+i, 0, prefix)
                        length = round(value * width / peak)
                        attr = curses.color_pair(i+1) | curses.A_BOLD if colors else 0
                        safe_add(win, 4+i, len(prefix), '█' * length, attr)
                    safe_add(win, 13, 0, f'Clear: {clear if clear is not None else "--":>5}    NIR: {nir if nir is not None else "--":>5}')
                    if max(vals) >= 65000 or (vals.count(0) >= 2 and max(vals) > 1000):
                        safe_add(win, 14, 0, 'INVALID-looking readings: press Z (reset sensor)')
                else:
                    safe_add(win, 4, 0, 'Waiting for first valid reading...')
            if last_error:
                safe_add(win, win.getmaxyx()[0]-3, 0, f'I2C read issue: {last_error}')
                safe_add(win, win.getmaxyx()[0]-2, 0, 'Last good values retained, retrying...')
            safe_add(win, win.getmaxyx()[0]-1, 0, f'Q / Y / Esc: back | I2C retry errors: {hiccups}')
            win.refresh()
    finally:
        try:
            if flicker_mode:
                reset_as7341_mode()
        except Exception:
            pass
        try:
            sensor.led = False
        except Exception:
            pass
        win.timeout(-1)


def menu(win):
    curses.curs_set(0)
    selected = 0
    while True:
        win.erase()
        safe_add(win,0,0,'PT35 Hardware Tools',curses.A_BOLD)
        safe_add(win,1,0,'Arrow keys / X B: move | Enter / A: select | Q / Y: exit')
        for i,(label,_) in enumerate(DEVICES):
            safe_add(win,i+3,0,('> ' if i==selected else '  ')+label,
                     curses.A_REVERSE if i==selected else 0)
        win.refresh()
        key=win.getch()
        if key in (curses.KEY_UP,ord('x'),ord('X')):
            selected=(selected-1)%len(DEVICES)
        elif key in (curses.KEY_DOWN,ord('b'),ord('B')):
            selected=(selected+1)%len(DEVICES)
        elif key in (ord('q'),ord('Q'),ord('y'),ord('Y'),27):
            return
        elif key in (10,13,curses.KEY_ENTER,ord('a'),ord('A')):
            action=DEVICES[selected][1]
            if action=='exit': return
            if action=='as7341': sensor_page(win)
            elif action=='nfc': page(win,'ST25DV16K NFC tag',[
                'Known I2C address: 0x57 (user memory interface).',
                'NFC mailbox / tag commands will reuse your existing NFC menu.',
                'This version does not change tag configuration.'])
            elif action=='reader': page(win,'ST25R3916 reader',[
                'Not installed yet. Reader controls will be added later.'])
            elif action=='neo': page(win,'NeoPixels',[
                'Hardware-specific LED control not wired in yet.',
                'Avoid concurrent access with pt35-leds.service.'])
            elif action=='led': page(win,'LED diagnostics',[
                'Needs the interface used by pt35-leds.service.',
                'No LED output was altered.'])
            elif action=='i2c':
                found=scan_bus()
                if found is None:
                    page(win,'I2C scan',['smbus2 missing. Install with:',
                                          '~/as7341-env/bin/pip install smbus2'])
                else:
                    page(win,'I2C bus 1', ['Found: '+', '.join(f'0x{x:02X}' for x in found),
                         'Busy devices may not respond to generic probes.',
                         '0x39 AS7341; 0x57 ST25DV16K'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ssh',action='store_true',help='Force terminal mode (default when a TTY exists)')
    parser.add_argument('--device',choices=['as7341'],help='Open directly into a tool')
    args=parser.parse_args()
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print('Interactive terminal required. For SSH use: ssh -t host pt35-tools')
        return 2
    if args.device=='as7341':
        curses.wrapper(sensor_page)
    else:
        curses.wrapper(menu)
    return 0

if __name__=='__main__':
    sys.exit(main())
