from machine import Pin, PWM, SPI
from micropython import const
import bluetooth
import time
import uasyncio as asio
from neopixel import NeoPixel

from BLEUART import BLEUART
from mfrc522 import MFRC522

# ---------- ПИНЫ ----------
LEFT_PWM_PIN = 5
LEFT_IN1_PIN = 16
LEFT_IN2_PIN = 17
RIGHT_PWM_PIN = 33
RIGHT_IN1_PIN = 32
RIGHT_IN2_PIN = 15
STBY_PIN = 13

GRIP_SERVO_PIN = 12
BUCKET_SERVO_PIN = 14

RFID_SCK  = 18
RFID_MOSI = 23
RFID_MISO = 4
RFID_CS   = 22
RFID_RST  = 21

LED_PIN = 27
NUM_LEDS = 8

BLE_NAME = "RASKOL_BOT"

DRIVE_SPEED = 900
TURN_SPEED  = 900

GRIP_TYPE = "360"
BUCKET_TYPE = "180"

SERVO_FREQ = 50
SERVO_MIN_DUTY = 20
SERVO_MAX_DUTY = 120
GRIP_OPEN_ANGLE = 110
GRIP_CLOSED_ANGLE = 55
BUCKET_MIN_ANGLE = 20
BUCKET_MAX_ANGLE = 160
BUCKET_START_ANGLE = 90
BUCKET_STEP = 10

SERVO_STOP_DUTY = 77
SERVO_FULL_SPEED_DUTY = 20
SERVO_REVERSE_SPEED_DUTY = 120

GRIP_CLOSE_TIME_MS = 500
GRIP_OPEN_TIME_MS = 500
BUCKET_MOVE_TIME_MS = 300

LOOP_DELAY_MS  = const(20)
LED_PULSE_MS   = const(150)
LED_SHOW_MS    = 5000          # лента горит 5 секунд

# ---------- КЛАСС TB6612 ----------
class TB6612:
    def __init__(self, pwm_pin, in1_pin, in2_pin, freq=1000):
        self.pwm = PWM(Pin(pwm_pin, Pin.OUT), freq=freq, duty=0)
        self.in1 = Pin(in1_pin, Pin.OUT)
        self.in2 = Pin(in2_pin, Pin.OUT)
        self.stop()

    def stop(self):
        self.pwm.duty(0)
        self.in1.value(0)
        self.in2.value(0)

    def forward(self, speed=1023):
        self.in1.value(1)
        self.in2.value(0)
        self.pwm.duty(min(1023, max(0, speed)))

    def reverse(self, speed=1023):
        self.in1.value(0)
        self.in2.value(1)
        self.pwm.duty(min(1023, max(0, speed)))

# ---------- ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ----------
comand = ""
on = 0
bucket_angle = BUCKET_START_ANGLE
led_pulse_started = 0
led_off_ticks = 0

led = Pin(2, Pin.OUT)
led.value(0)

np = NeoPixel(Pin(LED_PIN), NUM_LEDS)

stby = Pin(STBY_PIN, Pin.OUT)
stby.value(1)

left_motor  = TB6612(LEFT_PWM_PIN, LEFT_IN1_PIN, LEFT_IN2_PIN)
right_motor = TB6612(RIGHT_PWM_PIN, RIGHT_IN1_PIN, RIGHT_IN2_PIN)

grip_pwm = PWM(Pin(GRIP_SERVO_PIN, Pin.OUT))
grip_pwm.freq(SERVO_FREQ)
bucket_pwm = PWM(Pin(BUCKET_SERVO_PIN, Pin.OUT))
bucket_pwm.freq(SERVO_FREQ)

# Принудительная инициализация пинов RFID
_cs = Pin(RFID_CS, Pin.OUT)
_cs.value(1)
_rst = Pin(RFID_RST, Pin.OUT)
_rst.value(1)
time.sleep_ms(50)

spi_rfid = SPI(2, sck=Pin(RFID_SCK), mosi=Pin(RFID_MOSI), miso=Pin(RFID_MISO))
rfid = MFRC522(spi=spi_rfid, gpioRst=_rst, gpioCs=_cs)

# ---------- ЦВЕТА МЕТОК ----------
COLOR_MAP = {
    "white":  (255, 255, 255),
    "black":  (0, 0, 0),
    "red":    (255, 0, 0),
    "yellow": (255, 255, 0),
    "blue":   (0, 0, 255),
    "green":  (0, 255, 0),
    "orange": (255, 165, 0),
    "pink":   (255, 105, 180),
    "purple": (128, 0, 128),
    "brown":  (139, 69, 19),
    "grey":   (128, 128, 128)
}

# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------
def clamp(value, low, high):
    return min(high, max(low, value))

def map_value(x, in_min, in_max, out_min, out_max):
    return int((x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min)

def servo_write_angle(pwm_pin, angle):
    angle = clamp(int(angle), 0, 180)
    duty = map_value(angle, 0, 180, SERVO_MIN_DUTY, SERVO_MAX_DUTY)
    pwm_pin.duty(duty)

def servo_speed(pwm_pin, duty):
    duty = clamp(int(duty), 20, 120)
    pwm_pin.duty(duty)

def servo_stop(pwm_pin):
    servo_speed(pwm_pin, SERVO_STOP_DUTY)

def grip_close():
    if GRIP_TYPE == "180":
        servo_write_angle(grip_pwm, GRIP_CLOSED_ANGLE)
    else:
        servo_speed(grip_pwm, SERVO_FULL_SPEED_DUTY)
        time.sleep_ms(GRIP_CLOSE_TIME_MS)
        servo_stop(grip_pwm)

def grip_open():
    if GRIP_TYPE == "180":
        servo_write_angle(grip_pwm, GRIP_OPEN_ANGLE)
    else:
        servo_speed(grip_pwm, SERVO_REVERSE_SPEED_DUTY)
        time.sleep_ms(GRIP_OPEN_TIME_MS)
        servo_stop(grip_pwm)

def bucket_move_up():
    global bucket_angle
    if BUCKET_TYPE == "180":
        bucket_angle = clamp(bucket_angle + BUCKET_STEP, BUCKET_MIN_ANGLE, BUCKET_MAX_ANGLE)
        servo_write_angle(bucket_pwm, bucket_angle)
    else:
        bucket_angle = clamp(bucket_angle + BUCKET_STEP, BUCKET_MIN_ANGLE, BUCKET_MAX_ANGLE)
        servo_speed(bucket_pwm, SERVO_FULL_SPEED_DUTY)
        time.sleep_ms(BUCKET_MOVE_TIME_MS)
        servo_stop(bucket_pwm)

def bucket_move_down():
    global bucket_angle
    if BUCKET_TYPE == "180":
        bucket_angle = clamp(bucket_angle - BUCKET_STEP, BUCKET_MIN_ANGLE, BUCKET_MAX_ANGLE)
        servo_write_angle(bucket_pwm, bucket_angle)
    else:
        bucket_angle = clamp(bucket_angle - BUCKET_STEP, BUCKET_MIN_ANGLE, BUCKET_MAX_ANGLE)
        servo_speed(bucket_pwm, SERVO_REVERSE_SPEED_DUTY)
        time.sleep_ms(BUCKET_MOVE_TIME_MS)
        servo_stop(bucket_pwm)

def set_led_color(color):
    global led_off_ticks
    try:
        np.fill(color)
        np.write()
        if color != (0, 0, 0):
            led_off_ticks = time.ticks_ms()
    except Exception as e:
        print("Ошибка LED:", e)

def pulse_led():
    global led_pulse_started
    led_pulse_started = time.ticks_ms()
    led.value(1)

def update_led():
    global led_off_ticks
    if led.value() == 1:
        now = time.ticks_ms()
        if time.ticks_diff(now, led_pulse_started) > LED_PULSE_MS:
            led.value(0)
    if led_off_ticks != 0 and time.ticks_diff(time.ticks_ms(), led_off_ticks) > LED_SHOW_MS:
        set_led_color((0, 0, 0))
        led_off_ticks = 0

def send_status(message):
    try:
        uart.write((message + "\r\n").encode())
    except Exception:
        pass

def normalize_command(raw_command):
    command = raw_command.strip().upper()
    if not command:
        return ""
    if command.startswith("!B") and len(command) > 2:
        command = command[2:]
    return command

def on_rx():
    global comand, on
    on = 1
    try:
        raw_data = uart.read()
        if not raw_data:
            return
        text = raw_data.decode()
        for line in text.replace("\r", "\n").split("\n"):
            normalized = normalize_command(line)
            if normalized:
                comand = normalized
                print("Получена команда:", comand)
    except Exception as e:
        print("Ошибка декодирования:", e)

def motors_stop():
    left_motor.stop()
    right_motor.stop()

def motors_forward(speed=DRIVE_SPEED):
    left_motor.forward(speed)
    right_motor.forward(speed)

def motors_backward(speed=DRIVE_SPEED):
    left_motor.reverse(speed)
    right_motor.reverse(speed)

def motors_left(speed=TURN_SPEED):
    left_motor.reverse(speed)
    right_motor.forward(speed)

def motors_right(speed=TURN_SPEED):
    left_motor.forward(speed)
    right_motor.reverse(speed)

def get_exact_text(chunks):
    full_data = bytearray()
    for c in chunks:
        full_data.extend(c)
    try:
        if b'T' not in full_data:
            return "Пустая метка"
        t_idx = full_data.index(b'T')
        payload_len = full_data[t_idx - 1]
        status_byte = full_data[t_idx + 1]
        lang_len = status_byte & 0x3F
        text_start = t_idx + 2 + lang_len
        pure_text_len = payload_len - (1 + lang_len)
        text_bytes = full_data[text_start : text_start + pure_text_len]
        return text_bytes.decode('utf-8').lower().strip()
    except Exception as e:
        print("Ошибка извлечения текста:", e)
        return ""

def read_rfid_text():
    set_led_color((0, 0, 0))
    time.sleep_ms(50)

    (stat, tag_type) = rfid.request(rfid.REQIDL)
    print("Request stat:", stat)
    if stat != rfid.OK:
        return None

    (stat, raw_uid) = rfid.anticoll()
    print("Anticoll stat:", stat)
    if stat != rfid.OK:
        return None

    print("UID:", [hex(b) for b in raw_uid])

    # Читаем блоки напрямую (как в тестовом скрипте)
    block4 = bytearray(16)
    block5 = bytearray(16)
    r4 = rfid.read(4, into=block4)
    r5 = rfid.read(5, into=block5)
    print("Read block 4:", r4, block4)
    print("Read block 5:", r5, block5)

    if r4 is None or r5 is None:
        return None

    return get_exact_text([block4, block5])

def grab_and_read_rfid():
    grip_close()
    tag_text = read_rfid_text()
    if tag_text:
        print("RFID метка:", tag_text)
        send_status("rfid=" + tag_text)
        rgb = COLOR_MAP.get(tag_text, (0, 255, 0))
        set_led_color(rgb)
    else:
        print("Метка не прочитана")
        send_status("rfid=no_tag")
        set_led_color((0, 0, 0))

def release_cube():
    grip_open()
    print("Захват открыт")
    send_status("released")

def bucket_up():
    bucket_move_up()
    print("Ковш вверх, угол:", bucket_angle)
    send_status("bucket=" + str(bucket_angle))

def bucket_down():
    bucket_move_down()
    print("Ковш вниз, угол:", bucket_angle)
    send_status("bucket=" + str(bucket_angle))

ble = bluetooth.BLE()
ble.config(gap_name=BLE_NAME)
uart = BLEUART(ble, name=BLE_NAME)
uart.irq(handler=on_rx)

motors_stop()
if GRIP_TYPE == "180":
    servo_write_angle(grip_pwm, GRIP_OPEN_ANGLE)
else:
    servo_stop(grip_pwm)

if BUCKET_TYPE == "180":
    servo_write_angle(bucket_pwm, BUCKET_START_ANGLE)
else:
    servo_stop(bucket_pwm)

set_led_color((0, 0, 0))

print("ESP32 BLE UART готов")
print("Имя BLE:", BLE_NAME)
print("Движение: 516-вперед, 615-назад, 414-влево, 315-вправо, 507/606-стоп")
print("Кнопки: 1-захват+RFID, 2-разжать, 3-ковш вверх, 4-ковш вниз")
send_status("ready")

async def do_it(int_ms):
    global comand, on
    while True:
        await asio.sleep_ms(int_ms)

        if comand == "516":
            motors_forward()
            pulse_led()
            send_status("move=forward")
            comand = ""
        elif comand == "615":
            motors_backward()
            pulse_led()
            send_status("move=backward")
            comand = ""
        elif comand == "414":
            motors_left()
            pulse_led()
            send_status("move=left")
            comand = ""
        elif comand == "315":
            motors_right()
            pulse_led()
            send_status("move=right")
            comand = ""
        elif comand in ("507", "606", "STOP"):
            motors_stop()
            pulse_led()
            send_status("move=stop")
            comand = ""
        elif comand == "1":
            pulse_led()
            grab_and_read_rfid()
            comand = ""
        elif comand == "2":
            pulse_led()
            release_cube()
            comand = ""
        elif comand == "3":
            pulse_led()
            bucket_up()
            comand = ""
        elif comand == "4":
            pulse_led()
            bucket_down()
            comand = ""

        update_led()

loop = asio.get_event_loop()
loop.create_task(do_it(LOOP_DELAY_MS))

try:
    loop.run_forever()
except Exception:
    motors_stop()
    if GRIP_TYPE == "360":
        servo_stop(grip_pwm)
    if BUCKET_TYPE == "360":
        servo_stop(bucket_pwm)
    set_led_color((0, 0, 0))
    uart.close()
