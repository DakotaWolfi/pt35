#!/usr/bin/env python3
import time
from rpi_ws281x import PixelStrip, Color

LED_COUNT = 16
LED_PIN = 12
LED_FREQ_HZ = 800000
LED_DMA = 10
LED_BRIGHTNESS = 64
LED_INVERT = False
LED_CHANNEL = 0

strip = PixelStrip(
    LED_COUNT,
    LED_PIN,
    LED_FREQ_HZ,
    LED_DMA,
    LED_INVERT,
    LED_BRIGHTNESS,
    LED_CHANNEL
)

strip.begin()

def fill(color):
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, color)
    strip.show()

try:
    print("Red")
    fill(Color(255, 0, 0))
    time.sleep(1)

    print("Green")
    fill(Color(0, 255, 0))
    time.sleep(1)

    print("Blue")
    fill(Color(0, 0, 255))
    time.sleep(1)

    print("White")
    fill(Color(255, 255, 255))
    time.sleep(1)

    print("Rainbow chase")
    for offset in range(64):
        for i in range(strip.numPixels()):
            pos = (i * 256 // strip.numPixels() + offset * 4) & 255

            if pos < 85:
                c = Color(pos * 3, 255 - pos * 3, 0)
            elif pos < 170:
                pos -= 85
                c = Color(255 - pos * 3, 0, pos * 3)
            else:
                pos -= 170
                c = Color(0, pos * 3, 255 - pos * 3)

            strip.setPixelColor(i, c)

        strip.show()
        time.sleep(0.03)

finally:
    fill(Color(0, 0, 0))
