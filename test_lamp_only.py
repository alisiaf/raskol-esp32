from machine import Pin
from neopixel import NeoPixel
from time import sleep_ms

LED_PIN = 25
NUM_LEDS = 8

np = NeoPixel(Pin(LED_PIN, Pin.OUT), NUM_LEDS)


def set_color(color):
    np.fill(color)
    np.write()


print("NeoPixel lamp test started")
print("Pin:", LED_PIN, "LED count:", NUM_LEDS)

colors = [
    ("off", (0, 0, 0)),
    ("red", (40, 0, 0)),
    ("green", (0, 40, 0)),
    ("blue", (0, 0, 40)),
    ("yellow", (30, 30, 0)),
    ("purple", (20, 0, 30)),
    ("cyan", (0, 28, 28)),
    ("white", (35, 35, 35)),
]

while True:
    for name, color in colors:
        print("Color:", name, color)
        set_color(color)
        sleep_ms(1200)
