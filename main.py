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
STBY_PIN = 5

GRIP_SERVO_PIN = 26        # Клешня (360°)
BUCKET_SERVO_PIN = 27      # Ковш (360°)

RFID_SCK  = 4
RFID_MOSI = 33
RFID_MISO = 19
RFID_CS   = 18
RFID_RST  = 21

LED_PIN = 25
NUM_LEDS = 8

BLE_NAME = "RASKOL_BOT"

# Скорости моторов
LEFT_DRIVE_SPEED = 900
RIGHT_DRIVE_SPEED = 900
TURN_SPEED = 900

# ---------- ТИПЫ СЕРВОПРИВОДОВ (оба 360°) ----------
GRIP_TYPE = "360"
BUCKET_TYPE = "360"

# ---------- ПАРАМЕТРЫ ----------
SERVO_FREQ = 50
SERVO_MIN_DUTY = 20
SERVO_MAX_DUTY = 120

# Нейтрали
GRIP_STOP_DUTY = 77        # если ползёт – подберите 70-80
BUCKET_STOP_DUTY = 77      # если ползёт – подберите 70-80

# Клешня
GRIP_CLOSE_DUTY = 40       # Закрытие (ранее 20 – не хватало мощности)
GRIP_OPEN_DUTY = 120       # Открытие
GRIP_CLOSE_TIME_MS = 400
GRIP_OPEN_TIME_MS = 400

# Ковш
BUCKET_UP_DUTY = 40        # Поднять
BUCKET_DOWN_DUTY = 120     # Опустить
BUCKET_MOVE_TIME_MS = 300  # Время одного движения

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
command_queue = []          # очередь команд
bucket_angle = 90           # виртуальный угол для отображения (не управляет)
led_pulse_started = 0
led_off_ticks = 0
rfid_text = ""

# ---------- ИНИЦИАЛИЗАЦИЯ ОБЪЕКТОВ ----------
led = Pin(2, Pin.OUT)
led.value(0)

np = NeoPixel(Pin(LED_PIN), NUM_LEDS)

stby = Pin(STBY_PIN, Pin.OUT)
stby.value(1)

left_motor  = TB6612(LEFT_PWM_PIN, LEFT_IN1_PIN, LEFT_IN2_PIN)
right_motor = TB6612(RIGHT_PWM_PIN, RIGHT_IN1_PIN, RIGHT_IN2_PIN)

# Серво
grip_pwm = PWM(Pin(GRIP_SERVO_PIN, Pin.OUT))
grip_pwm.freq(SERVO_FREQ)
servo_stop(grip_pwm, GRIP_STOP_DUTY)       # клешня остановлена

bucket_pwm = PWM(Pin(BUCKET_SERVO_PIN, Pin.OUT))
bucket_pwm.freq(SERVO_FREQ)
servo_stop(bucket_pwm, BUCKET_STOP_DUTY)   # ковш остановлен

# RFID
_cs = Pin(RFID_CS, Pin.OUT); _cs.value(1)
_rst = Pin(RFID_RST, Pin.OUT); _rst.value(1)
time.sleep_ms(50)
spi_rfid = SPI(2, sck=Pin(RFID_SCK), mosi=Pin(RFID_MOSI), miso=Pin(RFID_MISO))
rfid = MFRC522(spi=spi_rfid, gpioRst=_rst, gpioCs=_cs)

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

# ---------- КЛЕШНЯ (360°) ----------
def grip_close():
    servo_speed(grip_pwm, GRIP_CLOSE_DUTY)
    time.sleep_ms(GRIP_CLOSE_TIME_MS)
    servo_stop(grip_pwm, GRIP_STOP_DUTY)

def grip_open():
    servo_speed(grip_pwm, GRIP_OPEN_DUTY)
    time.sleep_ms(GRIP_OPEN_TIME_MS)
    servo_stop(grip_pwm, GRIP_STOP_DUTY)

# ---------- КОВШ (360°) ----------
def bucket_move_up():
    global bucket_angle
    servo_speed(bucket_pwm, BUCKET_UP_DUTY)
    time.sleep_ms(BUCKET_MOVE_TIME_MS)
    servo_stop(bucket_pwm, BUCKET_STOP_DUTY)
    bucket_angle = min(bucket_angle + 10, 160)   # виртуальный угол для вывода

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
def get_exact_text(chunks):
    full_data = bytearray()
    for c in chunks:
        full_data.extend(c)
    try:
        if b'T' not in full_data:
            return ""
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

async def scan_rfid_task():
    global rfid_text
    while True:
        disable_neopixel()
        time.sleep_ms(50)

        (stat, tag_type) = rfid.request(rfid.REQIDL)
        if stat == rfid.OK:
            (stat, raw_uid) = rfid.anticoll()
            if stat == rfid.OK:
                if rfid.select_tag(raw_uid) == rfid.OK:
                    block4 = bytearray(16)
                    block5 = bytearray(16)
                    if rfid.read(4, into=block4) is not None and rfid.read(5, into=block5) is not None:
                        text = get_exact_text([block4, block5])
                        if text:
                            rfid_text = text
                            print(f"RFID прочитан: {rfid_text}")
                    rfid.stop_crypto1()

        enable_neopixel()
        await asio.sleep_ms(100)

def grab_and_read_rfid():
    grip_close()
    global rfid_text
    if rfid_text:
        print("RFID метка:", rfid_text)
        send_status("rfid=" + rfid_text)
        rgb = COLOR_MAP.get(rfid_text, (0, 255, 0))
        set_led_color(rgb)
    else:
        print("Метка не прочитана")
        send_status("rfid=no_tag")
        set_led_color((40, 0, 40))

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

        # Обрабатываем все накопленные команды
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
loop.create_task(scan_rfid_task())

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
        led.value(not led.value())
        time.sleep_ms(200)
        
