#!/usr/bin/env python3
"""Waveshare 2.13-inch e-Paper V4 test on Orange Pi Zero 3W (A733).

Wiring: SPI3 CS0 /dev/spidev3.0, DC=PE11(line139), RST=PD0(line96),
BUSY=PB6(line38), all on gpiochip0. Physical header pins 24,15,22,35.
VCC=3.3V. Run as root for the first test.

Controller init sequence is adapted from Waveshare's epd2in13_V4.py
(MIT licensed, Copyright Waveshare; original in their e-Paper GitHub).
"""
import time
import argparse

import gpiod
from gpiod.line import Direction, Value
import spidev
from PIL import Image, ImageDraw, ImageFont

CHIP = "/dev/gpiochip0"
DC, RST, BUSY = 139, 96, 38
WIDTH, HEIGHT = 122, 250  # native orientation

class Epaper:
    def __init__(self):
        self.lines = None
        self.spi = None

    def __enter__(self):
        self.lines = gpiod.request_lines(
            CHIP, consumer="fmi-epaper-v4",
            config={
                DC: gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.INACTIVE),
                RST: gpiod.LineSettings(direction=Direction.OUTPUT, output_value=Value.ACTIVE),
                BUSY: gpiod.LineSettings(direction=Direction.INPUT),
            },
        )
        try:
            self.spi = spidev.SpiDev()
            self.spi.open(3, 0)
            self.spi.max_speed_hz = 2_000_000
            self.spi.mode = 0
            self.spi.bits_per_word = 8
            return self
        except Exception:
            self.lines.release()
            raise

    def __exit__(self, *_):
        if self.spi is not None:
            self.spi.close()
        if self.lines is not None:
            self.lines.release()

    def gpio(self, pin, high):
        self.lines.set_value(pin, Value.ACTIVE if high else Value.INACTIVE)

    def wait_ready(self, timeout=30):
        end = time.monotonic() + timeout
        while self.lines.get_value(BUSY) == Value.ACTIVE:
            if time.monotonic() > end:
                raise TimeoutError("E-paper BUSY stayed HIGH for 30s: check wiring/panel")
            time.sleep(.02)

    def send(self, command, data=b""):
        self.gpio(DC, False)
        self.spi.writebytes([command])
        if data:
            self.gpio(DC, True)
            for start in range(0, len(data), 2048):
                self.spi.writebytes2(list(data[start:start+2048]))

    def init(self):
        self.gpio(RST, True)
        time.sleep(.020)
        self.gpio(RST, False)
        time.sleep(.002)
        self.gpio(RST, True)
        time.sleep(.020)
        self.wait_ready()
        self.send(0x12)  # SWRESET
        self.wait_ready()
        self.send(0x01, bytes([0xF9,0x00,0x00]))
        self.send(0x11, bytes([0x03]))
        self.send(0x44, bytes([0, (WIDTH-1)//8]))
        self.send(0x45, bytes([0,0,(HEIGHT-1)&255,(HEIGHT-1)>>8]))
        self.send(0x4E, bytes([0]))
        self.send(0x4F, bytes([0,0]))
        self.send(0x3C, bytes([0x05]))
        self.send(0x21, bytes([0,0x80]))
        self.send(0x18, bytes([0x80]))
        self.wait_ready()

    def display(self, image):
        if image.size == (HEIGHT, WIDTH):
            image = image.rotate(90, expand=True)
        if image.size != (WIDTH, HEIGHT):
            raise ValueError(f"Image size must be {WIDTH}x{HEIGHT} or {HEIGHT}x{WIDTH}")
        # Row pad to 16 bytes: 122 active pixels + 6 white padding pixels.
        img = image.convert("1")
        packed = bytearray()
        for y in range(HEIGHT):
            for x in range(0, 128, 8):
                byte = 0
                for bit in range(8):
                    px = x + bit
                    white = px >= WIDTH or img.getpixel((px,y)) != 0
                    if white:
                        byte |= 0x80 >> bit
                packed.append(byte)
        self.send(0x24, packed)
        self.send(0x22, bytes([0xF7]))
        self.send(0x20)
        self.wait_ready()

    def sleep(self):
        self.send(0x10, bytes([0x01]))

def test_image():
    img = Image.new("1", (HEIGHT, WIDTH), 1)
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, 249, 24), fill=0)
    draw.text((12, 7), "FMI PRINT STATION", fill=1)
    draw.text((16, 37), "ORANGE PI ZERO 3W", fill=0)
    draw.text((16, 60), "E-PAPER V4 TEST", fill=0)
    draw.line((10, 85, 239, 85), fill=0)
    draw.text((58, 99), "AWOOOO! :3", fill=0)
    return img

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true",
                        help="Save test PNG without accessing GPIO/SPI")
    args = parser.parse_args()
    img = test_image()
    if args.preview:
        img.save("/tmp/fmi-epaper-test.png")
        print("Saved /tmp/fmi-epaper-test.png")
        return
    print("Initializing Waveshare 2.13-inch V4 on SPI3…", flush=True)
    with Epaper() as epd:
        epd.init()
        print("Transferring framebuffer…", flush=True)
        epd.display(img)
        print("Screen update complete.", flush=True)
        epd.sleep()

if __name__ == "__main__":
    main()
