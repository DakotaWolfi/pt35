import board
import adafruit_as7341

sensor = adafruit_as7341.AS7341(board.I2C())

while True:
    print(sensor.all_channels)
