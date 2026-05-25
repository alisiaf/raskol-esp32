from machine import Pin, PWM, SPI
from micropython import const
import bluetooth
import time
import uasyncio as asio
from neopixel import NeoPixel

from BLEUART import BLEUART
from mfrc522 import MFRC522

# ---------- ПИНЫ ----------
LEFT_PWM_PIN = 13
LEFT_IN1_PIN = 12
LEFT_IN2_PIN = 14
RIGHT_PWM_PIN = 15
RIGHT_IN1_PIN = 16
RIGHT_IN2_PIN = 17
STBY_PIN = 18

GRIP_SERVO_PIN = 26        # Клешня
BUCKET_SERVO_PIN = 27      # Подъем

RFID_SCK  = 2
RFID_MOSI = 33
RFID_MISO = 19
RFID_CS   = 5
RFID_RST  = 21

LED_PIN = 25
NUM_LEDS = 8

BLE_NAME = "RASKOL_BOT"

# Скорости моторов
LEFT_DRIVE_SPEED = 900
RIGHT_DRIVE_SPEED = 900
TURN_SPEED = 900

# ---------- ПАРАМЕТРЫ ----------
SERVO_FREQ = 50
SERVO_MIN_DUTY = 20
SERVO_MAX_DUTY = 120

# Клешня. Оставляем управление по времени, как в исходной рабочей версии.
GRIP_STOP_DUTY = 77
GRIP_CLOSE_DUTY = 40
GRIP_OPEN_DUTY = 120
GRIP_CLOSE_TIME_MS = 400
GRIP_OPEN_TIME_MS = 400

# Подъем. Не менять, эта логика у вас работала.
BUCKET_STOP_DUTY = 77
BUCKET_UP_DUTY = 40
BUCKET_DOWN_DUTY = 120
BUCKET_MOVE_TIME_MS = 300

RFID_READ_ATTEMPTS = 8
RFID_RETRY_DELAY_MS = 60
RFID_READ_BLOCKS = (4, 5, 6, 8)

LOOP_DELAY_MS  = const(20)
LED_PULSE_MS   = const(150)
LED_SHOW_MS    = 3000

# ---------- ПРИНУДИТЕЛЬНЫЙ СБРОС ПИНОВ ДРАЙВЕРА ----------
for p in [LEFT_PWM_PIN, LEFT_IN1_PIN, LEFT_IN2_PIN,
          RIGHT_PWM_PIN, RIGHT_IN1_PIN, RIGHT_IN2_PIN, STBY_PIN]:
    Pin(p, Pin.OUT).value(0)

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

# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------
def clamp(value, low, high):
    return min(high, max(low, value))

def servo_speed(pwm_pin, duty):
    duty = clamp(int(duty), 20, 120)
    pwm_pin.duty(duty)

def servo_stop(pwm_pin, stop_duty):
    servo_speed(pwm_pin, stop_duty)

# ---------- ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ----------
command_queue = []
bucket_angle = 90
led_pulse_started = 0
led_off_ticks = 0

# ---------- ИНИЦИАЛИЗАЦИЯ ОБЪЕКТОВ ----------
led = None

np = NeoPixel(Pin(LED_PIN), NUM_LEDS)

stby = Pin(STBY_PIN, Pin.OUT)
stby.value(1)

left_motor  = TB6612(LEFT_PWM_PIN, LEFT_IN1_PIN, LEFT_IN2_PIN)
right_motor = TB6612(RIGHT_PWM_PIN, RIGHT_IN1_PIN, RIGHT_IN2_PIN)

grip_pwm = PWM(Pin(GRIP_SERVO_PIN, Pin.OUT))
grip_pwm.freq(SERVO_FREQ)
servo_stop(grip_pwm, GRIP_STOP_DUTY)

bucket_pwm = PWM(Pin(BUCKET_SERVO_PIN, Pin.OUT))
bucket_pwm.freq(SERVO_FREQ)
servo_stop(bucket_pwm, BUCKET_STOP_DUTY)

_cs = Pin(RFID_CS, Pin.OUT)
_cs.value(1)
_rst = Pin(RFID_RST, Pin.OUT)
_rst.value(1)
time.sleep_ms(50)
spi_rfid = SPI(2, sck=Pin(RFID_SCK), mosi=Pin(RFID_MOSI), miso=Pin(RFID_MISO))
rfid = MFRC522(spi=spi_rfid, gpioRst=_rst, gpioCs=_cs)

COLOR_MAP = {
    "white":  (40, 40, 40),
    "black":  (0, 0, 0),
    "red":    (40, 0, 0),
    "yellow": (32, 32, 0),
    "blue":   (0, 0, 40),
    "green":  (0, 40, 0),
    "orange": (40, 16, 0),
    "pink":   (40, 10, 20),
    "purple": (20, 0, 30),
    "brown":  (24, 10, 4),
    "grey":   (20, 20, 20)
}
KNOWN_COLORS = tuple(COLOR_MAP.keys())

# ---------- УПРАВЛЕНИЕ NEOPIXEL ----------
def disable_neopixel():
    try:
        np.fill((0, 0, 0))
        np.write()
    except:
        pass
    Pin(LED_PIN, Pin.IN)

def enable_neopixel():
    global np
    try:
        np = NeoPixel(Pin(LED_PIN, Pin.OUT), NUM_LEDS)
        np.fill((0, 0, 0))
        np.write()
    except Exception as e:
        print("Ошибка восстановления NeoPixel:", e)

# ---------- КЛЕШНЯ ----------
def grip_close():
    servo_speed(grip_pwm, GRIP_CLOSE_DUTY)
    time.sleep_ms(GRIP_CLOSE_TIME_MS)
    servo_stop(grip_pwm, GRIP_STOP_DUTY)

def grip_open():
    servo_speed(grip_pwm, GRIP_OPEN_DUTY)
    time.sleep_ms(GRIP_OPEN_TIME_MS)
    servo_stop(grip_pwm, GRIP_STOP_DUTY)

# ---------- ПОДЪЕМ ----------
def bucket_move_up():
    global bucket_angle
    servo_speed(bucket_pwm, BUCKET_UP_DUTY)
    time.sleep_ms(BUCKET_MOVE_TIME_MS)
    servo_stop(bucket_pwm, BUCKET_STOP_DUTY)
    bucket_angle = min(bucket_angle + 10, 160)

def bucket_move_down():
    global bucket_angle
    servo_speed(bucket_pwm, BUCKET_DOWN_DUTY)
    time.sleep_ms(BUCKET_MOVE_TIME_MS)
    servo_stop(bucket_pwm, BUCKET_STOP_DUTY)
    bucket_angle = max(bucket_angle - 10, 20)

# ---------- LED ЛЕНТА ----------
def set_led_color(color):
    global led_off_ticks
    try:
        np.fill(color)
        np.write()
        if color != (0, 0, 0):
            led_off_ticks = time.ticks_ms()
        else:
            led_off_ticks = 0
    except Exception as e:
        print("Ошибка LED:", e)

def pulse_led():
    global led_pulse_started
    led_pulse_started = time.ticks_ms()
    if led is not None:
        led.value(1)

def update_led():
    global led_off_ticks
    if led is not None and led.value() == 1:
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
    global command_queue
    try:
        raw_data = uart.read()
        if not raw_data:
            return
        text = raw_data.decode()
        for line in text.replace("\r", "\n").split("\n"):
            normalized = normalize_command(line)
            if normalized:
                command_queue.append(normalized)
                print("Получена команда:", normalized)
    except Exception as e:
        print("Ошибка декодирования:", e)

# ---------- ДВИЖЕНИЕ ----------
def motors_stop():
    left_motor.stop()
    right_motor.stop()

def motors_forward():
    left_motor.forward(LEFT_DRIVE_SPEED)
    right_motor.forward(RIGHT_DRIVE_SPEED)

def motors_backward():
    left_motor.reverse(LEFT_DRIVE_SPEED)
    right_motor.reverse(RIGHT_DRIVE_SPEED)

def motors_left():
    left_motor.reverse(TURN_SPEED)
    right_motor.forward(TURN_SPEED)

def motors_right():
    left_motor.forward(TURN_SPEED)
    right_motor.reverse(TURN_SPEED)

# ---------- RFID ----------
def bytes_to_safe_ascii(data):
    chars = []
    for b in data:
        if 32 <= b <= 126:
            chars.append(chr(b))
        else:
            chars.append(" ")
    return "".join(chars)

def make_utf16le_pattern(text):
    pattern = bytearray()
    for ch in text:
        pattern.append(ord(ch))
        pattern.append(0)
    return bytes(pattern)

def extract_color_fallback(chunks):
    merged = bytearray()
    for chunk in chunks:
        merged.extend(chunk)

    merged_bytes = bytes(merged)
    for color in KNOWN_COLORS:
        if color.encode() in merged_bytes:
            return color
        if make_utf16le_pattern(color) in merged_bytes:
            return color

    safe_text = bytes_to_safe_ascii(merged).lower()
    for color in KNOWN_COLORS:
        if color in safe_text:
            return color
    return ""

def decode_ndef_text(data):
    try:
        if b'T' not in data:
            return ""
        t_idx = data.index(b'T')
        payload_len = data[t_idx - 1]
        status_byte = data[t_idx + 1]
        lang_len = status_byte & 0x3F
        text_start = t_idx + 2 + lang_len
        pure_text_len = payload_len - (1 + lang_len)
        text_bytes = data[text_start : text_start + pure_text_len]

        decoded = bytes_to_safe_ascii(text_bytes).strip().lower()
        if decoded in KNOWN_COLORS:
            return decoded
        return ""
    except Exception as e:
        print("Ошибка извлечения текста:", e)
        return ""

def get_exact_text(chunks):
    merged = bytearray()
    for chunk in chunks:
        merged.extend(chunk)

    text = extract_color_fallback(chunks)
    if text:
        return text

    text = decode_ndef_text(merged)
    if text:
        return text

    for chunk in chunks:
        text = decode_ndef_text(chunk)
        if text:
            return text

    return ""

def read_rfid_text_once():
    (stat, tag_type) = rfid.request(rfid.REQIDL)
    if stat != rfid.OK:
        return None

    (stat, raw_uid) = rfid.anticoll()
    if stat != rfid.OK:
        return None

    if rfid.select_tag(raw_uid) != rfid.OK:
        return None

    chunks = []
    for block_num in RFID_READ_BLOCKS:
        block = bytearray(16)
        if rfid.read(block_num, into=block) is not None:
            chunks.append(block)

    rfid.stop_crypto1()
    if not chunks:
        return None
    text = get_exact_text(chunks)
    return text if text else None

def read_rfid_text_now():
    disable_neopixel()
    time.sleep_ms(50)
    try:
        for _ in range(RFID_READ_ATTEMPTS):
            text = read_rfid_text_once()
            if text:
                return text
            time.sleep_ms(RFID_RETRY_DELAY_MS)
    finally:
        enable_neopixel()
    return None

def grab_and_read_rfid():
    grip_close()
    tag_text = read_rfid_text_now()
    if tag_text:
        print("RFID метка:", tag_text)
        send_status("rfid=" + tag_text)
        rgb = COLOR_MAP.get(tag_text, (0, 255, 0))
        set_led_color(rgb)
    else:
        print("Метка не прочитана")
        send_status("rfid=no_tag")
        set_led_color((0, 28, 28))

def release_cube():
    grip_open()
    print("Захват открыт")
    send_status("released")

def bucket_up():
    bucket_move_up()
    print("Ковш вверх, виртуальный угол:", bucket_angle)
    send_status("bucket=" + str(bucket_angle))

def bucket_down():
    bucket_move_down()
    print("Ковш вниз, виртуальный угол:", bucket_angle)
    send_status("bucket=" + str(bucket_angle))

# ---------- BLE ----------
ble = bluetooth.BLE()
ble.config(gap_name=BLE_NAME)
uart = BLEUART(ble, name=BLE_NAME)
uart.irq(handler=on_rx)

motors_stop()
set_led_color((0, 0, 0))

print("ESP32 BLE UART готов")
print("Имя BLE:", BLE_NAME)
send_status("ready")

# ---------- АСИНХРОННЫЙ ЦИКЛ ----------
async def do_it(int_ms):
    global command_queue
    while True:
        await asio.sleep_ms(int_ms)

        while command_queue:
            comand = command_queue.pop(0)

            if comand in ("1", "10;", "10:"):
                print("Кнопка 1: захват и чтение RFID")
                pulse_led()
                grab_and_read_rfid()
            elif comand in ("219", "20;", "20:"):
                print("Кнопка 2: разжатие")
                pulse_led()
                release_cube()
            elif comand in ("318", "30;", "30:"):
                print("Кнопка 3: ковш вверх")
                pulse_led()
                bucket_up()
            elif comand in ("417", "40;", "40:"):
                print("Кнопка 4: ковш вниз")
                pulse_led()
                bucket_down()
            elif comand == "516":
                print("Вперед")
                motors_forward()
                pulse_led()
                send_status("move=forward")
            elif comand == "615":
                print("Назад")
                motors_backward()
                pulse_led()
                send_status("move=backward")
            elif comand == "714":
                print("Влево")
                motors_left()
                pulse_led()
                send_status("move=left")
            elif comand == "813":
                print("Вправо")
                motors_right()
                pulse_led()
                send_status("move=right")
            elif comand in ("507", "606", "705", "804", "STOP"):
                print("Стоп")
                motors_stop()
                pulse_led()
                send_status("move=stop")
            elif comand in ("11:", "21:", "31:", "41:", "309", "408"):
                pass
            else:
                print("Неизвестная команда:", comand)

        update_led()

# ---------- ЗАПУСК ----------
loop = asio.get_event_loop()
loop.create_task(do_it(LOOP_DELAY_MS))

try:
    loop.run_forever()
except Exception as e:
    print("КРИТИЧЕСКАЯ ОШИБКА:", e)
    motors_stop()
    servo_stop(grip_pwm, GRIP_STOP_DUTY)
    servo_stop(bucket_pwm, BUCKET_STOP_DUTY)
    set_led_color((0, 0, 0))
    uart.close()
    while True:
        if led is not None:
            led.value(not led.value())
        time.sleep_ms(200)

